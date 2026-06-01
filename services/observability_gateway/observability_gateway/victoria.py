import json
import os
import re
from datetime import datetime, timedelta
from uuid import UUID

import httpx

SINCE_PATTERN = re.compile(r"^\d+[smhd]$")
ENVIRONMENT_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]+$")
METRIC_QUERIES = {
    "request_rate": "sum(rate(todo_api_http_server_requests[1m]))",
    "error_rate": "sum(rate(todo_api_http_server_errors[1m]))",
    "duration_ms": (
        "sum(rate(todo_api_http_server_duration_sum[1m])) / "
        "sum(rate(todo_api_http_server_duration_count[1m]))"
    ),
}


class BackendIssueNotFoundError(Exception):
    """Raised when VictoriaLogs has no `unhandled_exception` log for an issue."""

    pass


def environment_value(name: str, default: str) -> str:
    """Return a trimmed environment variable or its fallback value.

    Args:
        name: Environment variable to read.
        default: Value returned when the variable is absent, empty, or only
            contains whitespace.

    Returns:
        The trimmed configured value, or `default`.

    Example:
        An empty `VICTORIA_LOGS_URL` returns `http://localhost:9428` when that
        URL is passed as `default`.
    """

    value = os.environ.get(name, default).strip()
    return value or default


class VictoriaBackendDiagnostics:
    """Read-only adapter for backend diagnostics stored in Victoria services.

    It uses fixed LogsQL and PromQL templates to:

    - list `unhandled_exception` logs from VictoriaLogs
    - fetch logs and Jaeger trace spans related to one backend issue
    - fetch request, error, and duration metric series around the issue timestamp

    Callers may choose filters such as lookback duration, result limit, and
    workload run ID. They cannot submit arbitrary LogsQL or PromQL.

    Example:
        `VictoriaBackendDiagnostics().list_issues(since="15m", limit=20,
        run_id=None)` lists recent local backend failures.
    """

    def __init__(
        self,
        *,
        logs_url: str | None = None,
        traces_url: str | None = None,
        metrics_url: str | None = None,
        environment: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        """Configure Victoria service URLs, environment filtering, and HTTP.

        Args:
            logs_url: VictoriaLogs base URL. When omitted, read
                `VICTORIA_LOGS_URL`, falling back to `http://localhost:9428`.
            traces_url: VictoriaTraces base URL. When omitted, read
                `VICTORIA_TRACES_URL`, falling back to `http://localhost:10428`.
            metrics_url: VictoriaMetrics base URL. When omitted, read
                `VICTORIA_METRICS_URL`, falling back to `http://localhost:8428`.
            environment: Environment included in every LogsQL query. When
                omitted, read `DIAGNOSTICS_ENVIRONMENT`, falling back to
                `local`.
            client: HTTP client used for Victoria requests. When omitted,
                create a client with a ten-second timeout. Tests can pass a
                client with `httpx.MockTransport` to avoid network requests.

        Raises:
            ValueError: `environment` contains characters outside letters,
                numbers, `.`, `_`, and `-`.

        Example:
            `VictoriaBackendDiagnostics(environment="local")` queries the
            default local Victoria URLs and adds `environment:local` to each
            LogsQL expression.
        """

        self._logs_url = (
            logs_url
            or environment_value("VICTORIA_LOGS_URL", "http://localhost:9428")
        ).rstrip("/")
        self._traces_url = (
            traces_url
            or environment_value("VICTORIA_TRACES_URL", "http://localhost:10428")
        ).rstrip("/")
        self._metrics_url = (
            metrics_url
            or environment_value("VICTORIA_METRICS_URL", "http://localhost:8428")
        ).rstrip("/")
        self._environment = environment or environment_value(
            "DIAGNOSTICS_ENVIRONMENT", "local"
        )
        if ENVIRONMENT_PATTERN.fullmatch(self._environment) is None:
            raise ValueError("diagnostics environment contains unsupported characters")
        self._client = client or httpx.Client(timeout=10)

    def close(self) -> None:
        """Close the HTTP client used for Victoria service requests."""

        self._client.close()

    def list_issues(
        self, *, since: str, limit: int, run_id: str | None
    ) -> list[dict[str, object]]:
        """List recent backend issue summaries from VictoriaLogs.

        This method builds a fixed LogsQL query for `unhandled_exception`
        records in the configured environment. A workload run ID narrows the
        query when present.

        Args:
            since: Relative lookback duration such as `15m`. Values must be a
                positive integer followed by `s`, `m`, `h`, or `d`.
            limit: Maximum number of summaries to request, from 1 through 100.
            run_id: Optional workload UUID. When omitted, the query does not
                filter by workload run.

        Returns:
            Lightweight backend issue summaries without stacktraces or related
            telemetry.

        Example:
            `list_issues(since="30m", limit=5, run_id=None)` returns at most
            five failures from the configured environment.
        """

        if SINCE_PATTERN.fullmatch(since) is None:
            raise ValueError("since must be a duration such as 15m")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

        query = (
            f"_time:{since} event_type:unhandled_exception "
            f"environment:{self._environment}"
        )
        if run_id is not None:
            query += f" run_id:{UUID(run_id)}"

        return [
            self._summary_from_log(log)
            for log in self._query_logs(query, limit=limit)
        ]

    def get_issue(self, issue_id: str) -> dict[str, object]:
        """Return bounded diagnostic context for one backend issue.

        This method:
        1. fetches the matching `unhandled_exception` log from VictoriaLogs
        2. fetches up to 100 logs sharing its trace ID within a ten-minute window
        3. fetches all Jaeger spans for the matching trace
        4. fetches fixed request, error, and duration metric series for the same
           window

        Args:
            issue_id: Backend issue identifier in `backend:<uuid>` format.

        Returns:
            A record with these top-level fields:

            - `summary`: the lightweight issue record
            - `stacktrace`: the complete exception stacktrace
            - `logs`: up to 100 logs sharing the trace ID
            - `spans`: all Jaeger spans for the trace ID
            - `metrics`: fixed metric series sampled once per minute from five
              minutes before through five minutes after the issue timestamp

        Raises:
            BackendIssueNotFoundError: VictoriaLogs has no matching issue log.
            ValueError: The issue ID or stored trace ID is malformed.

        Example:
            `get_issue("backend:00000000-0000-0000-0000-000000000123")`
            expands that specific failure without accepting a caller-provided
            LogsQL or PromQL expression.
        """

        self._validate_issue_id(issue_id)
        issue_logs = self._query_logs(
            (
                "event_type:unhandled_exception "
                f'environment:{self._environment} issue_id:"{issue_id}"'
            ),
            limit=1,
        )
        if not issue_logs:
            raise BackendIssueNotFoundError(issue_id)

        issue_log = issue_logs[0]
        trace_id = str(issue_log["trace_id"])
        if TRACE_ID_PATTERN.fullmatch(trace_id) is None:
            raise ValueError("backend issue has an invalid trace ID")

        timestamp = self._parse_timestamp(str(issue_log["_time"]))
        start = timestamp - timedelta(minutes=5)
        end = timestamp + timedelta(minutes=5)
        start_value = self._format_timestamp(start)
        end_value = self._format_timestamp(end)

        logs = self._query_logs(
            (
                f"_time:[{start_value},{end_value}] "
                f"environment:{self._environment} trace_id:{trace_id}"
            ),
            limit=100,
        )[:100]
        spans = self._query_trace_spans(trace_id)
        metrics = {
            name: self._query_metric(query, start=start_value, end=end_value)
            for name, query in METRIC_QUERIES.items()
        }
        return {
            "summary": self._summary_from_log(issue_log),
            "stacktrace": issue_log["stacktrace"],
            "logs": logs,
            "spans": spans,
            "metrics": {
                "start": start_value,
                "end": end_value,
                "step_seconds": 60,
                "series": metrics,
            },
            "trace_correlation": {
                "trace_id": trace_id,
                "source": "backend_trace_context",
            },
        }

    def _query_logs(self, query: str, *, limit: int) -> list[dict[str, object]]:
        """Execute one internally-built LogsQL query and parse its NDJSON rows.

        Args:
            query: LogsQL expression built by this adapter from validated
                filters. This private method is not exposed to Gateway callers.
            limit: Maximum number of log rows requested from VictoriaLogs.

        Returns:
            Parsed VictoriaLogs rows in response order.
        """

        response = self._client.post(
            f"{self._logs_url}/select/logsql/query",
            data={"query": query, "limit": str(limit)},
        )
        response.raise_for_status()
        return self._logs_from(response)

    def _query_trace_spans(self, trace_id: str) -> list[dict[str, object]]:
        """Return all Jaeger spans stored for one validated trace ID.

        Args:
            trace_id: Lowercase hexadecimal trace ID read from the issue log.

        Returns:
            Spans from the first matching trace, or an empty list when
            VictoriaTraces has no matching trace.
        """

        response = self._client.get(
            f"{self._traces_url}/select/jaeger/api/traces/{trace_id}"
        )
        response.raise_for_status()
        traces = response.json()["data"]
        return traces[0]["spans"] if traces else []

    def _query_metric(self, query: str, *, start: str, end: str) -> list[object]:
        """Return one fixed PromQL metric series sampled once per minute.

        Args:
            query: PromQL expression selected from `METRIC_QUERIES`.
            start: Inclusive metrics window start timestamp.
            end: Inclusive metrics window end timestamp.

        Returns:
            VictoriaMetrics range-query result rows.
        """

        response = self._client.get(
            f"{self._metrics_url}/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "step": "60"},
        )
        response.raise_for_status()
        return response.json()["data"]["result"]

    @staticmethod
    def _logs_from(response: httpx.Response) -> list[dict[str, object]]:
        """Parse non-empty NDJSON lines from a VictoriaLogs response."""

        return [
            json.loads(line) for line in response.text.splitlines() if line.strip()
        ]

    @staticmethod
    def _validate_issue_id(issue_id: str) -> None:
        """Reject identifiers that do not use the `backend:<uuid>` format.

        Args:
            issue_id: Identifier supplied by the Gateway issue detail route.

        Raises:
            ValueError: The identifier has another prefix or the suffix is not
                a UUID.

        Example:
            `backend:00000000-0000-0000-0000-000000000123` is accepted;
            `flutter:123` is rejected.
        """

        prefix, separator, identifier = issue_id.partition(":")
        if prefix != "backend" or not separator:
            raise ValueError("backend issue ID must use the backend:<uuid> format")
        UUID(identifier)

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        """Parse an ISO 8601 timestamp, including timestamps ending in `Z`."""

        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @staticmethod
    def _format_timestamp(value: datetime) -> str:
        """Format an ISO 8601 timestamp using `Z` for the UTC offset."""

        return value.isoformat().replace("+00:00", "Z")

    @staticmethod
    def _summary_from_log(log: dict[str, object]) -> dict[str, object]:
        """Copy the lightweight issue fields from an exception log.

        Args:
            log: Parsed `unhandled_exception` log from VictoriaLogs.

        Returns:
            Issue summary without stacktrace or related telemetry. The optional
            `run_id` is included only when it exists in the stored log.
        """

        summary = {
            "issue_id": log["issue_id"],
            "timestamp": log["_time"],
            "service": log["service"],
            "exception_type": log["exception_type"],
            "message": log["message"],
            "trace_id": log["trace_id"],
            "request_id": log["request_id"],
        }
        if "run_id" in log:
            summary["run_id"] = log["run_id"]
        return summary
