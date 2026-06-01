from collections.abc import Iterator
import json
import logging
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from todo_api.main import app
from todo_api.observability import LOGGER_NAME


class EventHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, object]] = []

    def emit(self, record: logging.LogRecord) -> None:
        if isinstance(record.msg, dict):
            self.events.append(record.msg)


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv("TODO_DB_PATH", str(tmp_path / "todos.db"))
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def request_log_events() -> Iterator[list[dict[str, object]]]:
    handler = EventHandler()
    logger = logging.getLogger(LOGGER_NAME)
    logger.addHandler(handler)
    yield handler.events
    logger.removeHandler(handler)


def test_todo_crud_journey(client: TestClient) -> None:
    assert client.get("/todos").json() == []

    create_response = client.post("/todos", json={"title": "buy milk"})
    assert create_response.status_code == 201
    todo = create_response.json()
    assert todo == {"id": 1, "title": "buy milk", "completed": False}

    assert client.get("/todos").json() == [todo]

    complete_response = client.patch("/todos/1", json={"completed": True})
    assert complete_response.status_code == 200
    assert complete_response.json() == {**todo, "completed": True}

    delete_response = client.delete("/todos/1")
    assert delete_response.status_code == 204
    assert client.get("/todos").json() == []


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_missing_todo_returns_not_found(client: TestClient, method: str) -> None:
    kwargs = {"json": {"completed": True}} if method == "patch" else {}
    response = getattr(client, method)("/todos/999", **kwargs)

    assert response.status_code == 404
    assert response.json() == {"detail": "Todo not found"}


def test_title_must_not_be_empty(client: TestClient) -> None:
    response = client.post("/todos", json={"title": ""})

    assert response.status_code == 422


def test_todos_survive_app_restart(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TODO_DB_PATH", str(tmp_path / "todos.db"))

    with TestClient(app) as first_client:
        first_client.post("/todos", json={"title": "persist me"})

    with TestClient(app) as restarted_client:
        assert restarted_client.get("/todos").json() == [
            {"id": 1, "title": "persist me", "completed": False}
        ]


def test_request_log_contains_bounded_diagnostic_context(
    client: TestClient, request_log_events: list[dict[str, object]]
) -> None:
    run_id = str(uuid4())
    response = client.post(
        "/todos",
        json={"title": "password=keep-this-private"},
        headers={
            "authorization": "Bearer secret-token",
            "cookie": "session=secret-cookie",
            "x-workload-run-id": run_id,
        },
    )

    assert response.status_code == 201
    assert UUID(response.headers["x-request-id"])
    event = request_log_events[-1]
    assert event == {
        "_msg": "http_request_completed",
        "event_type": "http_request_completed",
        "service": "todo-api",
        "method": "POST",
        "path_template": "/todos",
        "status_code": 201,
        "duration_ms": event["duration_ms"],
        "trace_id": "",
        "request_id": response.headers["x-request-id"],
        "user_id": "demo-user",
        "release": "local",
        "environment": "local",
        "run_id": run_id,
    }
    serialized_event = json.dumps(event)
    assert "keep-this-private" not in serialized_event
    assert "secret-token" not in serialized_event
    assert "secret-cookie" not in serialized_event
    assert "password" not in serialized_event


def test_request_log_uses_path_template_and_filters_invalid_correlation_ids(
    client: TestClient, request_log_events: list[dict[str, object]]
) -> None:
    response = client.delete(
        "/todos/999",
        headers={"x-request-id": "not-a-uuid", "x-workload-run-id": "not-a-uuid"},
    )

    assert response.status_code == 404
    event = request_log_events[-1]
    assert event["path_template"] == "/todos/{todo_id}"
    assert event["request_id"] == response.headers["x-request-id"]
    assert UUID(str(event["request_id"]))
    assert "run_id" not in event


def test_unhandled_delete_failure_emits_backend_issue_log(
    tmp_path, monkeypatch, request_log_events: list[dict[str, object]]
) -> None:
    monkeypatch.setenv("TODO_DB_PATH", str(tmp_path / "todos.db"))
    run_id = str(uuid4())

    with TestClient(app, raise_server_exceptions=False) as test_client:
        create_response = test_client.post(
            "/todos", json={"title": f"crash todo {run_id}"}
        )
        todo_id = create_response.json()["id"]

        delete_response = test_client.delete(
            f"/todos/{todo_id}",
            headers={"x-workload-run-id": run_id},
        )

    assert delete_response.status_code == 500
    assert UUID(delete_response.headers["x-request-id"])

    exception_event = next(
        event
        for event in request_log_events
        if event["event_type"] == "unhandled_exception"
    )
    assert str(exception_event["issue_id"]).startswith("backend:")
    assert UUID(str(exception_event["issue_id"]).removeprefix("backend:"))
    assert exception_event == {
        "_msg": "unhandled_exception",
        "event_type": "unhandled_exception",
        "issue_id": exception_event["issue_id"],
        "service": "todo-api",
        "exception_type": "RuntimeError",
        "message": "todo deletion failed",
        "stacktrace": exception_event["stacktrace"],
        "trace_id": "",
        "request_id": delete_response.headers["x-request-id"],
        "status_code": 500,
        "user_id": "demo-user",
        "release": "local",
        "environment": "local",
        "run_id": run_id,
    }
    assert "RuntimeError: todo deletion failed" in str(exception_event["stacktrace"])
    serialized_event = json.dumps(exception_event)
    assert "crash todo" not in serialized_event

    completed_event = next(
        event
        for event in request_log_events
        if event["event_type"] == "http_request_completed"
        and event["method"] == "DELETE"
    )
    assert completed_event["event_type"] == "http_request_completed"
    assert completed_event["path_template"] == "/todos/{todo_id}"
    assert completed_event["status_code"] == 500
