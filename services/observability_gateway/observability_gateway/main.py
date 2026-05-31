from typing import Annotated, Protocol
from uuid import UUID

from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel

from observability_gateway.victoria import VictoriaBackendDiagnostics


class BackendIssueSummary(BaseModel):
    issue_id: str
    timestamp: str
    service: str
    exception_type: str
    message: str
    trace_id: str
    request_id: str
    run_id: str | None = None


class BackendDiagnostics(Protocol):
    def list_issues(
        self, *, since: str, limit: int, run_id: str | None
    ) -> list[dict[str, object]]: ...


def get_backend_diagnostics() -> BackendDiagnostics:
    return VictoriaBackendDiagnostics()


app = FastAPI(title="Observability Gateway")


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
