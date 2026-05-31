from collections.abc import Iterator

import pytest

from todo_api.database import connect, initialize_database
from todo_api.todo_persistence import Todo, TodoNotFoundError, TodoPersistence


@pytest.fixture
def persistence(tmp_path, monkeypatch) -> Iterator[TodoPersistence]:
    monkeypatch.setenv("TODO_DB_PATH", str(tmp_path / "todos.db"))
    initialize_database()
    with connect() as connection:
        yield TodoPersistence(connection)


def test_todo_persistence_crud(persistence: TodoPersistence) -> None:
    assert persistence.list() == []

    todo = persistence.create("buy milk")
    assert todo == Todo(id=1, title="buy milk", completed=False)
    assert persistence.list() == [todo]

    completed_todo = persistence.update(todo.id, completed=True)
    assert completed_todo == Todo(id=1, title="buy milk", completed=True)

    persistence.delete(todo.id)
    assert persistence.list() == []


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_missing_todo_raises_not_found(
    persistence: TodoPersistence, operation: str
) -> None:
    if operation == "update":
        with pytest.raises(TodoNotFoundError):
            persistence.update(999, completed=True)
    else:
        with pytest.raises(TodoNotFoundError):
            persistence.delete(999)
