import httpx
import pytest

from observability_gateway.sentry import (
    ClientIssueNotFoundError,
    SentryClientDiagnostics,
)

ISSUE_ID = "client:123"


def test_list_issues_uses_read_only_sentry_api_and_returns_client_summaries() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/0/organizations/demo-org/issues/":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "123",
                        "lastSeen": "2026-05-31T08:30:00Z",
                        "title": "StateError: temporary client exception",
                        "metadata": {
                            "type": "StateError",
                            "value": "temporary client exception",
                        },
                        "latestEvent": {"eventID": "evt-bound-123"},
                    }
                ],
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    diagnostics = SentryClientDiagnostics(
        api_url="https://sentry.io/api/0",
        auth_token="read-only-token",
        organization="demo-org",
        project="todo-flutter-macos",
        environment="local",
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )

    issues = diagnostics.list_issues(since="15m", limit=20, run_id=None)

    assert issues == [
        {
            "issue_id": "client:123",
            "timestamp": "2026-05-31T08:30:00Z",
            "service": "todo-flutter-macos",
            "exception_type": "StateError",
            "message": "temporary client exception",
            "event_id": "evt-bound-123",
        }
    ]
    assert len(requests) == 1
    assert requests[0].headers["authorization"] == "Bearer read-only-token"
    assert dict(requests[0].url.params) == {
        "query": "project:todo-flutter-macos",
        "environment": "local",
        "statsPeriod": "15m",
        "limit": "20",
    }


def test_get_issue_returns_bounded_stacktrace_breadcrumbs_and_client_context() -> None:
    requests: list[httpx.Request] = []
    breadcrumbs = [
        {"timestamp": f"2026-05-31T08:29:{index:02d}Z", "category": "navigation"}
        for index in range(120)
    ]

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "dateCreated": "2026-05-31T08:30:00Z",
                "title": "StateError: temporary client exception",
                "release": {"version": "dev-20260531-001"},
                "user": {"id": "demo-user"},
                "contexts": {
                    "trace": {
                        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
                        "span_id": "00f067aa0ba902b7",
                    }
                },
                "tags": [
                    {"key": "environment", "value": "local"},
                    {"key": "session_id", "value": "session-123"},
                ],
                "entries": [
                    {
                        "type": "exception",
                        "data": {
                            "values": [
                                {
                                    "type": "StateError",
                                    "value": "temporary client exception",
                                    "stacktrace": {
                                        "frames": [
                                            {
                                                "filename": "main.dart",
                                                "function": "main",
                                                "lineNo": 12,
                                            }
                                        ]
                                    },
                                }
                            ]
                        },
                    },
                    {"type": "breadcrumbs", "data": {"values": breadcrumbs}},
                ],
            },
        )

    diagnostics = SentryClientDiagnostics(
        api_url="https://sentry.io/api/0",
        auth_token="read-only-token",
        organization="demo-org",
        project="todo-flutter-macos",
        environment="local",
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )

    detail = diagnostics.get_issue(ISSUE_ID)

    assert detail["summary"] == {
        "issue_id": ISSUE_ID,
        "timestamp": "2026-05-31T08:30:00Z",
        "service": "todo-flutter-macos",
        "exception_type": "StateError",
        "message": "temporary client exception",
    }
    assert detail["stacktrace"] == [
        {"filename": "main.dart", "function": "main", "lineNo": 12}
    ]
    assert len(detail["breadcrumbs"]) == 100
    assert detail["breadcrumbs"][0] == breadcrumbs[20]
    assert detail["breadcrumbs"][-1] == breadcrumbs[-1]
    assert detail["context"] == {
        "release": "dev-20260531-001",
        "environment": "local",
        "user_id": "demo-user",
        "session_id": "session-123",
    }
    assert detail["trace_correlation"] == {
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "source": "sentry_trace_context",
    }
    assert len(requests) == 1
    assert (
        requests[0].url.path
        == "/api/0/organizations/demo-org/issues/123/events/latest/"
    )
    assert dict(requests[0].url.params) == {"environment": "local"}
    assert requests[0].headers["authorization"] == "Bearer read-only-token"


def test_get_issue_event_uses_bound_event_id_instead_of_latest_event() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/events/latest/"):
            return httpx.Response(
                200,
                json={
                    "dateCreated": "2026-05-31T08:45:00Z",
                    "title": "StateError: latest event",
                    "entries": [],
                },
            )
        assert (
            request.url.path
            == "/api/0/organizations/demo-org/issues/123/events/evt-bound-123/"
        )
        return httpx.Response(
            200,
            json={
                "dateCreated": "2026-05-31T08:30:00Z",
                "title": "StateError: bound client exception",
                "environment": "local",
                "entries": [
                    {
                        "type": "exception",
                        "data": {
                            "values": [
                                {
                                    "type": "StateError",
                                    "value": "bound client exception",
                                    "stacktrace": {
                                        "frames": [{"filename": "bound.dart"}]
                                    },
                                }
                            ]
                        },
                    },
                    {
                        "type": "breadcrumbs",
                        "data": {"values": [{"category": "http"}]},
                    },
                ],
                "contexts": {
                    "trace": {"trace_id": "11111111111111111111111111111111"}
                },
                "tags": [{"key": "session_id", "value": "session-bound"}],
            },
        )

    diagnostics = SentryClientDiagnostics(
        api_url="https://sentry.io/api/0",
        auth_token="read-only-token",
        organization="demo-org",
        project="todo-flutter-macos",
        environment="local",
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )

    detail = diagnostics.get_issue_event(ISSUE_ID, "evt-bound-123")

    assert detail["summary"] == {
        "issue_id": ISSUE_ID,
        "timestamp": "2026-05-31T08:30:00Z",
        "service": "todo-flutter-macos",
        "exception_type": "StateError",
        "message": "bound client exception",
    }
    assert detail["stacktrace"] == [{"filename": "bound.dart"}]
    assert detail["breadcrumbs"] == [{"category": "http"}]
    assert detail["context"] == {
        "release": None,
        "environment": "local",
        "user_id": None,
        "session_id": "session-bound",
    }
    assert detail["trace_correlation"] == {
        "trace_id": "11111111111111111111111111111111",
        "source": "sentry_trace_context",
    }
    assert [request.url.path for request in requests] == [
        "/api/0/organizations/demo-org/issues/123/events/evt-bound-123/"
    ]


def test_get_issue_reports_unknown_client_issue() -> None:
    diagnostics = SentryClientDiagnostics(
        api_url="https://sentry.io/api/0",
        auth_token="read-only-token",
        organization="demo-org",
        project="todo-flutter-macos",
        environment="local",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(404))
        ),
    )

    with pytest.raises(ClientIssueNotFoundError):
        diagnostics.get_issue("client:999")
