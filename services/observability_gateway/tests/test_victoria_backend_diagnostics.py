from urllib.parse import parse_qs

import httpx
import pytest

from observability_gateway.victoria import (
    BackendIssueNotFoundError,
    VictoriaBackendDiagnostics,
)

ISSUE_ID = "backend:00000000-0000-0000-0000-000000000123"


def test_list_issues_uses_fixed_logsql_template_and_defaults_to_local_environment() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            text=(
                '{"_time":"2026-05-31T08:30:00Z","issue_id":"backend:123",'
                '"service":"todo-api","exception_type":"RuntimeError",'
                '"message":"todo deletion failed","trace_id":"abc",'
                '"request_id":"request-123"}\n'
            ),
        )

    diagnostics = VictoriaBackendDiagnostics(
        logs_url="http://victoria-logs:9428",
        traces_url="http://victoria-traces:10428",
        metrics_url="http://victoria-metrics:8428",
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )

    issues = diagnostics.list_issues(since="15m", limit=20, run_id=None)

    assert issues == [
        {
            "issue_id": "backend:123",
            "timestamp": "2026-05-31T08:30:00Z",
            "service": "todo-api",
            "exception_type": "RuntimeError",
            "message": "todo deletion failed",
            "trace_id": "abc",
            "request_id": "request-123",
        }
    ]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "http://victoria-logs:9428/select/logsql/query"
    assert parse_qs(request.content.decode()) == {
        "query": ["_time:15m event_type:unhandled_exception environment:local"],
        "limit": ["20"],
    }


def test_get_issue_returns_bounded_logs_trace_spans_and_fixed_metrics_window() -> None:
    requests: list[httpx.Request] = []
    relevant_logs = "".join(
        f'{{"event_type":"http_request_completed","sequence":{index}}}\n'
        for index in range(120)
    )

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/select/logsql/query":
            form = parse_qs(request.content.decode())
            if form["limit"] == ["1"]:
                return httpx.Response(
                    200,
                    text=(
                        '{"_time":"2026-05-31T08:30:00Z",'
                        f'"issue_id":"{ISSUE_ID}",'
                        '"service":"todo-api","exception_type":"RuntimeError",'
                        '"message":"todo deletion failed","trace_id":"abc",'
                        '"request_id":"request-123",'
                        '"stacktrace":"line 1\\nline 2\\nline 3"}\n'
                    ),
                )
            return httpx.Response(200, text=relevant_logs)
        if request.url.path == "/select/jaeger/api/traces/abc":
            return httpx.Response(
                200,
                json={"data": [{"spans": [{"traceID": "abc", "operationName": "DELETE"}]}]},
            )
        if request.url.path == "/api/v1/query_range":
            return httpx.Response(200, json={"data": {"result": []}})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    diagnostics = VictoriaBackendDiagnostics(
        logs_url="http://victoria-logs:9428",
        traces_url="http://victoria-traces:10428",
        metrics_url="http://victoria-metrics:8428",
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )

    detail = diagnostics.get_issue(ISSUE_ID)

    assert detail["summary"] == {
        "issue_id": ISSUE_ID,
        "timestamp": "2026-05-31T08:30:00Z",
        "service": "todo-api",
        "exception_type": "RuntimeError",
        "message": "todo deletion failed",
        "trace_id": "abc",
        "request_id": "request-123",
    }
    assert detail["stacktrace"] == "line 1\nline 2\nline 3"
    assert len(detail["logs"]) == 100
    assert detail["logs"][0]["sequence"] == 0
    assert detail["logs"][-1]["sequence"] == 99
    assert detail["spans"] == [{"traceID": "abc", "operationName": "DELETE"}]
    assert detail["metrics"] == {
        "start": "2026-05-31T08:25:00Z",
        "end": "2026-05-31T08:35:00Z",
        "step_seconds": 60,
        "series": {
            "request_rate": [],
            "error_rate": [],
            "duration_ms": [],
        },
    }

    log_requests = [
        parse_qs(request.content.decode())
        for request in requests
        if request.url.path == "/select/logsql/query"
    ]
    assert log_requests == [
        {
            "query": [
                f'event_type:unhandled_exception environment:local issue_id:"{ISSUE_ID}"'
            ],
            "limit": ["1"],
        },
        {
            "query": [
                "_time:[2026-05-31T08:25:00Z,2026-05-31T08:35:00Z] "
                "environment:local trace_id:abc"
            ],
            "limit": ["100"],
        },
    ]

    metric_requests = [
        parse_qs(request.url.query.decode())
        for request in requests
        if request.url.path == "/api/v1/query_range"
    ]
    assert len(metric_requests) == 3
    assert [request["query"] for request in metric_requests] == [
        ["sum(rate(todo_api_http_server_requests[1m]))"],
        ["sum(rate(todo_api_http_server_errors[1m]))"],
        [
            "sum(rate(todo_api_http_server_duration_sum[1m])) / "
            "sum(rate(todo_api_http_server_duration_count[1m]))"
        ],
    ]
    assert all(
        request["start"] == ["2026-05-31T08:25:00Z"]
        and request["end"] == ["2026-05-31T08:35:00Z"]
        and request["step"] == ["60"]
        for request in metric_requests
    )


def test_get_issue_reports_unknown_backend_issue() -> None:
    diagnostics = VictoriaBackendDiagnostics(
        logs_url="http://victoria-logs:9428",
        traces_url="http://victoria-traces:10428",
        metrics_url="http://victoria-metrics:8428",
        client=httpx.Client(
            # A successful empty LogsQL response means the issue does not exist.
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text=""))
        ),
    )

    # pytest.raises uses a context manager to assert that this call raises the error.
    with pytest.raises(BackendIssueNotFoundError):
        diagnostics.get_issue(ISSUE_ID)
