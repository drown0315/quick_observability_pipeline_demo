import os
import sqlite3
from pathlib import Path

from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor

from todo_api.observability import observability


def database_path() -> Path:
    return Path(os.environ.get("TODO_DB_PATH", "todos.db"))


def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    if observability.tracer_provider is not None:
        connection = SQLite3Instrumentor().instrument_connection(
            connection, tracer_provider=observability.tracer_provider
        )
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
