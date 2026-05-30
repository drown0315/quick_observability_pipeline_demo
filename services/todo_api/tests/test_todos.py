from collections.abc import Iterator

from fastapi.testclient import TestClient
import pytest

from todo_api.main import app


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv("TODO_DB_PATH", str(tmp_path / "todos.db"))
    with TestClient(app) as test_client:
        yield test_client


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
