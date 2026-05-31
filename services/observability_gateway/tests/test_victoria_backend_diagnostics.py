from urllib.parse import parse_qs

import httpx

from observability_gateway.victoria import VictoriaBackendDiagnostics


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
