import sqlite3
from collections.abc import Iterator

from pydantic import BaseModel, ConfigDict

from todo_api.database import connect


class Todo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    completed: bool


class TodoNotFoundError(Exception):
    pass


class TodoPersistence:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def list(self) -> list[Todo]:
        rows = self._connection.execute(
            "SELECT id, title, completed FROM todos ORDER BY id"
        ).fetchall()
        return [self._todo_from_row(row) for row in rows]

    def create(self, title: str) -> Todo:
        cursor = self._connection.execute(
            "INSERT INTO todos (title) VALUES (?)",
            (title,),
        )
        self._connection.commit()
        return self._require(cursor.lastrowid)

    def update(self, todo_id: int, *, completed: bool) -> Todo:
        self._require(todo_id)
        self._connection.execute(
            "UPDATE todos SET completed = ? WHERE id = ?",
            (completed, todo_id),
        )
        self._connection.commit()
        return self._require(todo_id)

    def delete(self, todo_id: int) -> None:
        todo = self._require(todo_id)
        if "crash" in todo.title:
            raise RuntimeError("todo deletion failed")
        self._connection.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
        self._connection.commit()

    def _require(self, todo_id: int) -> Todo:
        row = self._connection.execute(
            "SELECT id, title, completed FROM todos WHERE id = ?",
            (todo_id,),
        ).fetchone()
        if row is None:
            raise TodoNotFoundError
        return self._todo_from_row(row)

    @staticmethod
    def _todo_from_row(row: sqlite3.Row) -> Todo:
        return Todo(
            id=row["id"],
            title=row["title"],
            completed=bool(row["completed"]),
        )


def get_todo_persistence() -> Iterator[TodoPersistence]:
    with connect() as connection:
        yield TodoPersistence(connection)
