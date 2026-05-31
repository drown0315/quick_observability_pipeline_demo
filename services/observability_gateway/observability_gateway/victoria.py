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
    pass


def environment_value(name: str, default: str) -> str:
    value = os.environ.get(name, default).strip()
    return value or default


class VictoriaBackendDiagnostics:
    def __init__(
        self,
        *,
        logs_url: str | None = None,
        traces_url: str | None = None,
        metrics_url: str | None = None,
        environment: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
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
        self._client.close()

    def list_issues(
        self, *, since: str, limit: int, run_id: str | None
    ) -> list[dict[str, object]]:
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
        }

    def _query_logs(self, query: str, *, limit: int) -> list[dict[str, object]]:
        response = self._client.post(
            f"{self._logs_url}/select/logsql/query",
            data={"query": query, "limit": str(limit)},
        )
        response.raise_for_status()
        return self._logs_from(response)

    def _query_trace_spans(self, trace_id: str) -> list[dict[str, object]]:
        response = self._client.get(
            f"{self._traces_url}/select/jaeger/api/traces/{trace_id}"
        )
        response.raise_for_status()
        traces = response.json()["data"]
        return traces[0]["spans"] if traces else []

    def _query_metric(self, query: str, *, start: str, end: str) -> list[object]:
        response = self._client.get(
            f"{self._metrics_url}/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "step": "60"},
        )
        response.raise_for_status()
        return response.json()["data"]["result"]

    @staticmethod
    def _logs_from(response: httpx.Response) -> list[dict[str, object]]:
        return [
            json.loads(line) for line in response.text.splitlines() if line.strip()
        ]

    @staticmethod
    def _validate_issue_id(issue_id: str) -> None:
        prefix, separator, identifier = issue_id.partition(":")
        if prefix != "backend" or not separator:
            raise ValueError("backend issue ID must use the backend:<uuid> format")
        UUID(identifier)

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @staticmethod
    def _format_timestamp(value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")

    @staticmethod
    def _summary_from_log(log: dict[str, object]) -> dict[str, object]:
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
