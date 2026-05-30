FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev

COPY todo_api ./todo_api

ENV TODO_DB_PATH=/data/todos.db

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "uvicorn", "todo_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
