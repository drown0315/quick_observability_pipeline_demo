from collections.abc import Iterator
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from observability_gateway.main import (
    app,
    get_backend_diagnostics,
    get_client_diagnostics,
)
from observability_gateway.sentry import ClientIssueNotFoundError
from observability_gateway.victoria import BackendIssueNotFoundError

ISSUE_ID = "backend:00000000-0000-0000-0000-000000000123"
UNKNOWN_ISSUE_ID = "backend:00000000-0000-0000-0000-000000000999"
CLIENT_ISSUE_ID = "client:123"
UNKNOWN_CLIENT_ISSUE_ID = "client:999"


@pytest.fixture
def backend_diagnostics() -> "StubBackendDiagnostics":
    return StubBackendDiagnostics()


@pytest.fixture
def client_diagnostics() -> "StubClientDiagnostics":
    return StubClientDiagnostics()


@pytest.fixture
def client(
    backend_diagnostics: "StubBackendDiagnostics",
    client_diagnostics: "StubClientDiagnostics",
) -> Iterator[TestClient]:
    """Inject the stub diagnostics adapter while one Gateway client is active."""

    app.dependency_overrides[get_backend_diagnostics] = lambda: backend_diagnostics
    app.dependency_overrides[get_client_diagnostics] = lambda: client_diagnostics
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class StubBackendDiagnostics:
    """Record route calls and return deterministic backend diagnostic records."""

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
        if issue_id == UNKNOWN_ISSUE_ID:
            raise BackendIssueNotFoundError(issue_id)
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


class StubClientDiagnostics:
    """Record route calls and return deterministic client diagnostic records."""

    def __init__(self) -> None:
        self.list_calls: list[dict[str, object]] = []
        self.show_calls: list[str] = []

    def list_issues(
        self, *, since: str, limit: int, run_id: str | None
    ) -> list[dict[str, object]]:
        self.list_calls.append({"since": since, "limit": limit, "run_id": run_id})
        return [
            {
                "issue_id": CLIENT_ISSUE_ID,
                "timestamp": "2026-05-31T08:31:00Z",
                "service": "todo-flutter-macos",
                "exception_type": "StateError",
                "message": "temporary client exception",
            }
        ]

    def get_issue(self, issue_id: str) -> dict[str, object]:
        self.show_calls.append(issue_id)
        if issue_id == UNKNOWN_CLIENT_ISSUE_ID:
            raise ClientIssueNotFoundError(issue_id)
        return {
            "summary": {
                "issue_id": issue_id,
                "timestamp": "2026-05-31T08:31:00Z",
                "service": "todo-flutter-macos",
                "exception_type": "StateError",
                "message": "temporary client exception",
            },
            "stacktrace": [{"filename": "main.dart", "lineNo": 12}],
            "breadcrumbs": [{"category": "navigation"}],
            "context": {
                "release": "dev-20260531-001",
                "environment": "local",
                "user_id": "demo-user",
                "session_id": "session-123",
            },
        }


def test_list_issues_supports_filters_and_returns_backend_and_client_summaries(
    client: TestClient,
    backend_diagnostics: StubBackendDiagnostics,
    client_diagnostics: StubClientDiagnostics,
) -> None:
    run_id = str(uuid4())

    response = client.get(
        "/diagnostics/issues",
        params={"since": "30m", "limit": 5, "run_id": run_id},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "issue_id": CLIENT_ISSUE_ID,
            "timestamp": "2026-05-31T08:31:00Z",
            "service": "todo-flutter-macos",
            "exception_type": "StateError",
            "message": "temporary client exception",
        },
        {
            "issue_id": ISSUE_ID,
            "timestamp": "2026-05-31T08:30:00Z",
            "service": "todo-api",
            "exception_type": "RuntimeError",
            "message": "todo deletion failed",
            "trace_id": "abc",
            "request_id": "request-123",
            "run_id": run_id,
        },
    ]
    assert backend_diagnostics.list_calls == [
        {"since": "30m", "limit": 5, "run_id": run_id}
    ]
    assert client_diagnostics.list_calls == [
        {"since": "30m", "limit": 5, "run_id": run_id}
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


def test_show_client_issue_returns_bounded_diagnostic_evidence(
    client: TestClient, client_diagnostics: StubClientDiagnostics
) -> None:
    response = client.get(f"/diagnostics/issues/{CLIENT_ISSUE_ID}")

    assert response.status_code == 200
    assert response.json() == {
        "summary": {
            "issue_id": CLIENT_ISSUE_ID,
            "timestamp": "2026-05-31T08:31:00Z",
            "service": "todo-flutter-macos",
            "exception_type": "StateError",
            "message": "temporary client exception",
        },
        "stacktrace": [{"filename": "main.dart", "lineNo": 12}],
        "breadcrumbs": [{"category": "navigation"}],
        "context": {
            "release": "dev-20260531-001",
            "environment": "local",
            "user_id": "demo-user",
            "session_id": "session-123",
        },
    }
    assert client_diagnostics.show_calls == [CLIENT_ISSUE_ID]


def test_show_backend_issue_rejects_invalid_issue_id(
    client: TestClient, backend_diagnostics: StubBackendDiagnostics
) -> None:
    response = client.get("/diagnostics/issues/not-a-backend-issue")

    assert response.status_code == 422
    assert backend_diagnostics.show_calls == []


def test_show_backend_issue_returns_not_found_for_unknown_issue(
    client: TestClient, backend_diagnostics: StubBackendDiagnostics
) -> None:
    response = client.get(f"/diagnostics/issues/{UNKNOWN_ISSUE_ID}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Backend issue not found"}
    assert backend_diagnostics.show_calls == [UNKNOWN_ISSUE_ID]


def test_show_client_issue_returns_not_found_for_unknown_issue(
    client: TestClient, client_diagnostics: StubClientDiagnostics
) -> None:
    response = client.get(f"/diagnostics/issues/{UNKNOWN_CLIENT_ISSUE_ID}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Client issue not found"}
    assert client_diagnostics.show_calls == [UNKNOWN_CLIENT_ISSUE_ID]


def test_health_check(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
