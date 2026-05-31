from collections.abc import Iterator
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from observability_gateway.main import app, get_backend_diagnostics

ISSUE_ID = "backend:00000000-0000-0000-0000-000000000123"


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
        self.show_calls: list[str] = []

    def list_issues(
        self, *, since: str, limit: int, run_id: str | None
    ) -> list[dict[str, object]]:
        self.list_calls.append({"since": since, "limit": limit, "run_id": run_id})
        return [
            {
                "issue_id": ISSUE_ID,
                "timestamp": "2026-05-31T08:30:00Z",
                "service": "todo-api",
                "exception_type": "RuntimeError",
                "message": "todo deletion failed",
                "trace_id": "abc",
                "request_id": "request-123",
                "run_id": run_id,
            }
        ]

    def get_issue(self, issue_id: str) -> dict[str, object]:
        self.show_calls.append(issue_id)
        return {
            "summary": {
                "issue_id": issue_id,
                "timestamp": "2026-05-31T08:30:00Z",
                "service": "todo-api",
                "exception_type": "RuntimeError",
                "message": "todo deletion failed",
                "trace_id": "abc",
                "request_id": "request-123",
            },
            "stacktrace": "Traceback (most recent call last):\nRuntimeError",
            "logs": [{"event_type": "unhandled_exception", "issue_id": issue_id}],
            "spans": [{"traceID": "abc", "operationName": "DELETE /todos/{todo_id}"}],
            "metrics": {
                "start": "2026-05-31T08:25:00Z",
                "end": "2026-05-31T08:35:00Z",
                "step_seconds": 60,
                "series": {"request_rate": []},
            },
        }


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
            "issue_id": ISSUE_ID,
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


def test_show_backend_issue_returns_bounded_diagnostic_evidence(
    client: TestClient, backend_diagnostics: StubBackendDiagnostics
) -> None:
    response = client.get(f"/diagnostics/issues/{ISSUE_ID}")

    assert response.status_code == 200
    assert response.json() == {
        "summary": {
            "issue_id": ISSUE_ID,
            "timestamp": "2026-05-31T08:30:00Z",
            "service": "todo-api",
            "exception_type": "RuntimeError",
            "message": "todo deletion failed",
            "trace_id": "abc",
            "request_id": "request-123",
            "run_id": None,
        },
        "stacktrace": "Traceback (most recent call last):\nRuntimeError",
        "logs": [{"event_type": "unhandled_exception", "issue_id": ISSUE_ID}],
        "spans": [{"traceID": "abc", "operationName": "DELETE /todos/{todo_id}"}],
        "metrics": {
            "start": "2026-05-31T08:25:00Z",
            "end": "2026-05-31T08:35:00Z",
            "step_seconds": 60,
            "series": {"request_rate": []},
        },
    }
    assert backend_diagnostics.show_calls == [ISSUE_ID]


def test_show_backend_issue_rejects_invalid_issue_id(
    client: TestClient, backend_diagnostics: StubBackendDiagnostics
) -> None:
    response = client.get("/diagnostics/issues/not-a-backend-issue")

    assert response.status_code == 422
    assert backend_diagnostics.show_calls == []
