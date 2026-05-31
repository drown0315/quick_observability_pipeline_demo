import json
import os
import re
from uuid import UUID

import httpx

SINCE_PATTERN = re.compile(r"^\d+[smhd]$")
ENVIRONMENT_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


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

        response = self._client.post(
            f"{self._logs_url}/select/logsql/query",
            data={"query": query, "limit": str(limit)},
        )
        response.raise_for_status()
        return [
            self._summary_from_log(json.loads(line))
            for line in response.text.splitlines()
            if line.strip()
        ]

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
