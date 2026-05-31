from collections.abc import Iterator
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from observability_gateway.main import app, get_backend_diagnostics


@pytest.fixture
def backend_diagnostics() -> "StubBackendDiagnostics":
    return StubBackendDiagnostics()


@pytest.fixture
def client(backend_diagnostics: "StubBackendDiagnostics") -> Iterator[TestClient]:
    app.dependency_overrides[get_backend_diagnostics] = lambda: backend_diagnostics
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class StubBackendDiagnostics:
    def __init__(self) -> None:
        self.list_calls: list[dict[str, object]] = []

    def list_issues(
        self, *, since: str, limit: int, run_id: str | None
    ) -> list[dict[str, object]]:
        self.list_calls.append({"since": since, "limit": limit, "run_id": run_id})
        return [
            {
                "issue_id": "backend:123",
                "timestamp": "2026-05-31T08:30:00Z",
                "service": "todo-api",
                "exception_type": "RuntimeError",
                "message": "todo deletion failed",
                "trace_id": "abc",
                "request_id": "request-123",
                "run_id": run_id,
            }
        ]


def test_list_backend_issues_supports_filters_and_returns_summaries(
    client: TestClient, backend_diagnostics: StubBackendDiagnostics
) -> None:
    run_id = str(uuid4())

    response = client.get(
        "/diagnostics/issues",
        params={"since": "30m", "limit": 1, "run_id": run_id},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "issue_id": "backend:123",
            "timestamp": "2026-05-31T08:30:00Z",
            "service": "todo-api",
            "exception_type": "RuntimeError",
            "message": "todo deletion failed",
            "trace_id": "abc",
            "request_id": "request-123",
            "run_id": run_id,
        }
    ]
    assert backend_diagnostics.list_calls == [
        {"since": "30m", "limit": 1, "run_id": run_id}
    ]
