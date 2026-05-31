from collections.abc import Iterator
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import Depends, FastAPI, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from observability_gateway.victoria import (
    BackendIssueNotFoundError,
    VictoriaBackendDiagnostics,
)


class BackendIssueSummary(BaseModel):
    """Small backend issue record returned by the issue list endpoint.

    It identifies one `unhandled_exception` log without including the
    stacktrace, related logs, trace spans, or metrics window.

    Example:
        A Todo deletion failure is represented by its `backend:<uuid>` issue
        ID, timestamp, exception type, trace ID, request ID, and optional
        workload run ID.
    """

    issue_id: str
    timestamp: str
    service: str
    exception_type: str
    message: str
    trace_id: str
    request_id: str
    run_id: str | None = None


class MetricsWindow(BaseModel):
    """Metric query results around the time when a backend issue occurred.

    It contains the inclusive time range, the sample interval in seconds, and
    the named VictoriaMetrics series returned for that range.

    Example:
        An issue at `08:30` returns samples from `08:25` through `08:35` with
        `step_seconds=60`.
    """

    start: str
    end: str
    step_seconds: int
    series: dict[str, object]


class BackendIssueDetail(BaseModel):
    """Complete bounded diagnostic response for one backend issue.

    The response has these top-level fields:

    - `summary`: the lightweight issue record also returned by the list endpoint
    - `stacktrace`: the complete exception stacktrace
    - `logs`: up to 100 related logs
    - `spans`: matching trace spans
    - `metrics`: metric samples around the issue timestamp

    Example:
        Expanding `backend:<uuid>` returns the deletion failure summary plus
        its related request logs, SQLite spans, and metric samples.
    """

    summary: BackendIssueSummary
    stacktrace: str
    logs: list[dict[str, object]]
    spans: list[dict[str, object]]
    metrics: MetricsWindow


class BackendDiagnostics(Protocol):
    """Read-only interface for querying normalized backend diagnostics.

    Implementations list lightweight backend issue summaries and expand one
    `backend:<uuid>` issue into bounded diagnostic context.

    Example:
        `VictoriaBackendDiagnostics` implements this interface by querying
        VictoriaLogs, VictoriaTraces, and VictoriaMetrics.
    """

    def list_issues(
        self, *, since: str, limit: int, run_id: str | None
    ) -> list[dict[str, object]]: ...

    def get_issue(self, issue_id: str) -> dict[str, object]: ...


def get_backend_diagnostics() -> Iterator[BackendDiagnostics]:
    """Provide one Victoria diagnostics adapter for the lifetime of a request.

    FastAPI advances this generator to obtain the adapter before calling the
    route, then closes the generator after the response is handled. The
    `finally` block closes the adapter's HTTP client even when route handling
    raises an exception.

    Yields:
        A read-only Victoria diagnostics adapter for the current request.

    Example:
        `Depends(get_backend_diagnostics)` injects one adapter into an issue
        list or issue detail route and closes it after that request finishes.
    """

    diagnostics = VictoriaBackendDiagnostics()
    try:
        yield diagnostics
    finally:
        diagnostics.close()


app = FastAPI(title="Observability Gateway")


@app.exception_handler(BackendIssueNotFoundError)
async def backend_issue_not_found(
    _: Request, __: BackendIssueNotFoundError
) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"detail": "Backend issue not found"},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/diagnostics/issues", response_model=list[BackendIssueSummary])
def list_issues(
    since: Annotated[str, Query(pattern=r"^\d+[smhd]$")] = "15m",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    run_id: UUID | None = None,
    diagnostics: BackendDiagnostics = Depends(get_backend_diagnostics),
) -> list[dict[str, object]]:
    """Return recent backend issue summaries that match the supplied filters.

    Args:
        since: Relative lookback duration such as `15m`. The HTTP layer accepts
            a positive integer followed by `s`, `m`, `h`, or `d`.
        limit: Maximum number of summaries to return. The accepted range is
            1 through 100.
        run_id: Optional workload UUID. When omitted, issues from all workload
            runs in the configured diagnostics environment are eligible.
        diagnostics: Read-only adapter used to query backend diagnostics.

    Returns:
        Lightweight issue records without stacktraces or related telemetry.

    Example:
        `/diagnostics/issues?since=30m&limit=5` returns at most five backend
        issue summaries observed during the last 30 minutes.
    """

    return diagnostics.list_issues(
        since=since,
        limit=limit,
        run_id=str(run_id) if run_id is not None else None,
    )


@app.get("/diagnostics/issues/{issue_id}", response_model=BackendIssueDetail)
def show_issue(
    issue_id: Annotated[
        str,
        Path(pattern=r"^backend:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"),
    ],
    diagnostics: BackendDiagnostics = Depends(get_backend_diagnostics),
) -> dict[str, object]:
    """Return bounded diagnostic context for one backend issue.

    Args:
        issue_id: Identifier in `backend:<uuid>` format. FastAPI rejects other
            formats before querying the diagnostics adapter.
        diagnostics: Read-only adapter used to retrieve issue context.

    Returns:
        One issue summary, its complete stacktrace, up to 100 related logs,
        matching trace spans, and a bounded metrics window.

    Example:
        `/diagnostics/issues/backend:00000000-0000-0000-0000-000000000123`
        expands that specific backend failure.
    """

    return diagnostics.get_issue(issue_id)
