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
    issue_id: str
    timestamp: str
    service: str
    exception_type: str
    message: str
    trace_id: str
    request_id: str
    run_id: str | None = None


class MetricsWindow(BaseModel):
    start: str
    end: str
    step_seconds: int
    series: dict[str, object]


class BackendIssueDetail(BaseModel):
    summary: BackendIssueSummary
    stacktrace: str
    logs: list[dict[str, object]]
    spans: list[dict[str, object]]
    metrics: MetricsWindow


class BackendDiagnostics(Protocol):
    def list_issues(
        self, *, since: str, limit: int, run_id: str | None
    ) -> list[dict[str, object]]: ...

    def get_issue(self, issue_id: str) -> dict[str, object]: ...


def get_backend_diagnostics() -> Iterator[BackendDiagnostics]:
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
    return diagnostics.get_issue(issue_id)
