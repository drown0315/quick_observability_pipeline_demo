import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
from threading import Thread
from urllib.parse import parse_qs, urlparse

import pytest

REPOSITORY_ROOT = Path(__file__).parents[3]
DIAGNOSTICS_SCRIPT = REPOSITORY_ROOT / "scripts" / "diagnostics"


@pytest.fixture
def gateway_server() -> tuple[str, list[str]]:
    requests: list[str] = []

    class GatewayHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            summary = {
                "issue_id": "backend:00000000-0000-0000-0000-000000000123",
                "timestamp": "2026-05-31T08:30:00Z",
                "service": "todo-api",
                "exception_type": "RuntimeError",
                "message": "todo deletion failed",
                "trace_id": "abc",
                "request_id": "request-123",
                "run_id": None,
            }
            value: object = [summary]
            if self.path.startswith("/diagnostics/issues/backend:"):
                value = {
                    "summary": summary,
                    "stacktrace": "line 1\nline 2",
                    "logs": [{"event_type": "unhandled_exception"}],
                    "spans": [{"operationName": "DELETE"}],
                    "metrics": {
                        "start": "2026-05-31T08:25:00Z",
                        "end": "2026-05-31T08:35:00Z",
                        "step_seconds": 60,
                        "series": {},
                    },
                }
            body = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", requests
    server.shutdown()
    thread.join()


def test_issues_command_outputs_json_by_default(
    gateway_server: tuple[str, list[str]],
) -> None:
    gateway_url, requests = gateway_server
    run_id = "00000000-0000-0000-0000-000000000456"

    result = subprocess.run(
        [
            sys.executable,
            str(DIAGNOSTICS_SCRIPT),
            "issues",
            "--since",
            "30m",
            "--limit",
            "5",
            "--run-id",
            run_id,
        ],
        check=False,
        capture_output=True,
        env={**os.environ, "DIAGNOSTICS_GATEWAY_URL": gateway_url},
        text=True,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == [
        {
            "issue_id": "backend:00000000-0000-0000-0000-000000000123",
            "timestamp": "2026-05-31T08:30:00Z",
            "service": "todo-api",
            "exception_type": "RuntimeError",
            "message": "todo deletion failed",
            "trace_id": "abc",
            "request_id": "request-123",
            "run_id": None,
        }
    ]
    parsed_request = urlparse(requests[0])
    assert parsed_request.path == "/diagnostics/issues"
    assert parse_qs(parsed_request.query) == {
        "since": ["30m"],
        "limit": ["5"],
        "run_id": [run_id],
    }


def test_show_command_supports_text_output(
    gateway_server: tuple[str, list[str]],
) -> None:
    gateway_url, requests = gateway_server
    issue_id = "backend:00000000-0000-0000-0000-000000000123"

    result = subprocess.run(
        [
            sys.executable,
            str(DIAGNOSTICS_SCRIPT),
            "show",
            issue_id,
            "--format",
            "text",
        ],
        check=False,
        capture_output=True,
        env={**os.environ, "DIAGNOSTICS_GATEWAY_URL": gateway_url},
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout == (
        f"Issue: {issue_id}\n"
        "Time: 2026-05-31T08:30:00Z\n"
        "Exception: RuntimeError: todo deletion failed\n"
        "\n"
        "Stacktrace:\n"
        "line 1\n"
        "line 2\n"
        "\n"
        "Logs: 1\n"
        "Spans: 1\n"
        "Metrics window: 2026-05-31T08:25:00Z to 2026-05-31T08:35:00Z\n"
    )
    assert requests == [f"/diagnostics/issues/{issue_id}"]
