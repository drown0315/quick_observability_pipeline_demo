from collections.abc import Iterator
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import Depends, FastAPI, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from observability_gateway.sentry import (
    ClientIssueNotFoundError,
    SentryClientDiagnostics,
)
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


class ClientIssueSummary(BaseModel):
    """Small Flutter client issue record returned by the issue list endpoint.

    It identifies one Sentry issue group without including its stacktrace or
    breadcrumbs.
    """

    issue_id: str
    timestamp: str
    service: str
    exception_type: str
    message: str


class ClientContext(BaseModel):
    """Flutter client context attached to one Sentry exception event."""

    release: str | None = None
    environment: str | None = None
    user_id: str | None = None
    session_id: str | None = None


class ClientIssueDetail(BaseModel):
    """Complete bounded diagnostic response for one Flutter client issue."""

    summary: ClientIssueSummary
    stacktrace: list[dict[str, object]]
    breadcrumbs: list[dict[str, object]]
    context: ClientContext


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


class ClientDiagnostics(Protocol):
    """Read-only interface for querying normalized Flutter client diagnostics."""

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


def get_client_diagnostics() -> Iterator[ClientDiagnostics]:
    """Provide one Sentry diagnostics adapter for the lifetime of a request."""

    diagnostics = SentryClientDiagnostics()
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


@app.exception_handler(ClientIssueNotFoundError)
async def client_issue_not_found(
    _: Request, __: ClientIssueNotFoundError
) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"detail": "Client issue not found"},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/diagnostics/issues",
    response_model=list[BackendIssueSummary | ClientIssueSummary],
)
def list_issues(
    since: Annotated[str, Query(pattern=r"^\d+[smhd]$")] = "15m",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    run_id: UUID | None = None,
    backend_diagnostics: BackendDiagnostics = Depends(get_backend_diagnostics),
    client_diagnostics: ClientDiagnostics = Depends(get_client_diagnostics),
) -> list[dict[str, object]]:
    """Return recent backend and Flutter client issues matching the filters.

    Args:
        since: Relative lookback duration such as `15m`. The HTTP layer accepts
            a positive integer followed by `s`, `m`, `h`, or `d`.
        limit: Maximum number of summaries to return. The accepted range is
            1 through 100.
        run_id: Optional workload UUID. When omitted, issues from all workload
            runs in the configured diagnostics environment are eligible.
        backend_diagnostics: Read-only adapter used to query backend issues.
        client_diagnostics: Read-only adapter used to query Flutter issues.

    Returns:
        Lightweight issue records without stacktraces or related evidence,
        ordered by most recent timestamp and bounded by `limit`.

    Example:
        `/diagnostics/issues?since=30m&limit=5` returns at most five backend
        and Flutter issue summaries observed during the last 30 minutes.
    """

    run_id_value = str(run_id) if run_id is not None else None
    issues = backend_diagnostics.list_issues(
        since=since,
        limit=limit,
        run_id=run_id_value,
    )
    issues += client_diagnostics.list_issues(
        since=since,
        limit=limit,
        run_id=run_id_value,
    )
    return sorted(issues, key=lambda issue: str(issue["timestamp"]), reverse=True)[
        :limit
    ]


@app.get(
    "/diagnostics/issues/{issue_id}",
    response_model=BackendIssueDetail | ClientIssueDetail,
)
def show_issue(
    issue_id: Annotated[
        str,
        Path(
            pattern=(
                r"^(backend:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
                r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|"
                r"client:\d+)$"
            )
        ),
    ],
    backend_diagnostics: BackendDiagnostics = Depends(get_backend_diagnostics),
    client_diagnostics: ClientDiagnostics = Depends(get_client_diagnostics),
) -> dict[str, object]:
    """Return bounded diagnostic context for one backend or Flutter issue.

    Args:
        issue_id: Identifier in `backend:<uuid>` or `client:<group-id>` format.
            FastAPI rejects other formats before querying an adapter.
        backend_diagnostics: Read-only adapter used to query backend issues.
        client_diagnostics: Read-only adapter used to query Flutter issues.

    Returns:
        One issue summary and its source-specific bounded evidence.

    Example:
        `/diagnostics/issues/backend:00000000-0000-0000-0000-000000000123`
        expands that specific backend failure.
    """

    if issue_id.startswith("backend:"):
        return backend_diagnostics.get_issue(issue_id)
    return client_diagnostics.get_issue(issue_id)
