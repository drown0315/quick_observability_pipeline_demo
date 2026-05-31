from contextlib import asynccontextmanager
from time import perf_counter
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel, Field

from todo_api.database import initialize_database
from todo_api.observability import SERVICE_NAME, observability
from todo_api.todo_persistence import (
    Todo,
    TodoNotFoundError,
    TodoPersistence,
    get_todo_persistence,
)

DEMO_USER_ID = "demo-user"


class TodoCreate(BaseModel):
    title: str = Field(min_length=1)


class TodoUpdate(BaseModel):
    completed: bool


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield
    observability.shutdown()


app = FastAPI(title="Todo API", lifespan=lifespan)


def validated_uuid(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def path_template(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


@app.middleware("http")
async def record_completed_request(request: Request, call_next) -> Response:
    if request.url.path == "/health":
        return await call_next(request)

    started_at = perf_counter()
    request_id = validated_uuid(request.headers.get("x-request-id")) or str(uuid4())
    run_id = validated_uuid(request.headers.get("x-workload-run-id"))
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["x-request-id"] = request_id
        return response
    finally:
        duration_ms = round((perf_counter() - started_at) * 1_000, 3)
        template = path_template(request)
        span = trace.get_current_span()
        span_context = span.get_span_context()
        trace_id = (
            f"{span_context.trace_id:032x}" if span_context.is_valid else ""
        )
        attributes = {
            "service": SERVICE_NAME,
            "method": request.method,
            "path_template": template,
            "status_code": status_code,
        }
        span.set_attributes(
            {
                **attributes,
                "request.id": request_id,
                "user.id": DEMO_USER_ID,
                **({"workload.run_id": run_id} if run_id is not None else {}),
            }
        )
        observability.request_counter.add(1, attributes)
        observability.request_duration.record(duration_ms, attributes)
        if status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            observability.error_counter.add(1, attributes)

        event = {
            "_msg": "http_request_completed",
            "event_type": "http_request_completed",
            **attributes,
            "duration_ms": duration_ms,
            "trace_id": trace_id,
            "request_id": request_id,
            "user_id": DEMO_USER_ID,
            "release": observability.release,
            "environment": observability.environment,
        }
        if run_id is not None:
            event["run_id"] = run_id
        observability.logger.info(event)


FastAPIInstrumentor.instrument_app(
    app,
    tracer_provider=observability.tracer_provider,
    meter_provider=observability.meter_provider,
    excluded_urls="/health",
    exclude_spans=["receive", "send"],
)


@app.exception_handler(TodoNotFoundError)
async def todo_not_found(_: Request, __: TodoNotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": "Todo not found"},
    )

def todo_from_row(row: sqlite3.Row) -> Todo:
    return Todo(id=row["id"], title=row["title"], completed=bool(row["completed"]))


def require_todo(connection: sqlite3.Connection, todo_id: int) -> sqlite3.Row:
    row = execute(
        connection,
        "SELECT id, title, completed FROM todos WHERE id = ?", (todo_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")
    return row

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/todos", response_model=list[Todo])
def list_todos(persistence: TodoPersistence = Depends(get_todo_persistence)) -> list[Todo]:
    return persistence.list()



@app.post("/todos", response_model=Todo, status_code=status.HTTP_201_CREATED)
def create_todo(
    request: TodoCreate,
    persistence: TodoPersistence = Depends(get_todo_persistence),
) -> Todo:
    return persistence.create(request.title)


@app.patch("/todos/{todo_id}", response_model=Todo)
def update_todo(
    todo_id: int,
    request: TodoUpdate,
    persistence: TodoPersistence = Depends(get_todo_persistence),
) -> Todo:
    return persistence.update(todo_id, completed=request.completed)


@app.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_todo(
    todo_id: int,
    persistence: TodoPersistence = Depends(get_todo_persistence),
) -> Response:
    persistence.delete(todo_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
