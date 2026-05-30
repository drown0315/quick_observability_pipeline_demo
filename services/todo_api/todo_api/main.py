from contextlib import asynccontextmanager
import sqlite3

from fastapi import Depends, FastAPI, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from todo_api.database import get_connection, initialize_database


class TodoCreate(BaseModel):
    title: str = Field(min_length=1)


class TodoUpdate(BaseModel):
    completed: bool


class Todo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    completed: bool


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Todo API", lifespan=lifespan)


def todo_from_row(row: sqlite3.Row) -> Todo:
    return Todo(id=row["id"], title=row["title"], completed=bool(row["completed"]))


def require_todo(connection: sqlite3.Connection, todo_id: int) -> sqlite3.Row:
    row = connection.execute(
        "SELECT id, title, completed FROM todos WHERE id = ?", (todo_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")
    return row


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/todos", response_model=list[Todo])
def list_todos(connection: sqlite3.Connection = Depends(get_connection)) -> list[Todo]:
    rows = connection.execute(
        "SELECT id, title, completed FROM todos ORDER BY id"
    ).fetchall()
    return [todo_from_row(row) for row in rows]


@app.post("/todos", response_model=Todo, status_code=status.HTTP_201_CREATED)
def create_todo(
    request: TodoCreate, connection: sqlite3.Connection = Depends(get_connection)
) -> Todo:
    cursor = connection.execute(
        "INSERT INTO todos (title) VALUES (?)",
        (request.title,),
    )
    connection.commit()
    return todo_from_row(require_todo(connection, cursor.lastrowid))


@app.patch("/todos/{todo_id}", response_model=Todo)
def update_todo(
    todo_id: int,
    request: TodoUpdate,
    connection: sqlite3.Connection = Depends(get_connection),
) -> Todo:
    require_todo(connection, todo_id)
    connection.execute(
        "UPDATE todos SET completed = ? WHERE id = ?",
        (request.completed, todo_id),
    )
    connection.commit()
    return todo_from_row(require_todo(connection, todo_id))


@app.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_todo(
    todo_id: int, connection: sqlite3.Connection = Depends(get_connection)
) -> Response:
    require_todo(connection, todo_id)
    connection.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    connection.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
