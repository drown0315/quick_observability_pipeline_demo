import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path


def database_path() -> Path:
    return Path(os.environ.get("TODO_DB_PATH", "todos.db"))


def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    with connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0
            )
            """
        )


def get_connection() -> Iterator[sqlite3.Connection]:
    with connect() as connection:
        yield connection
