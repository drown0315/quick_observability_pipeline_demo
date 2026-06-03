import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
from threading import Thread
from typing import Iterator
from urllib.parse import parse_qs, urlparse

import pytest

SERVICE_ROOT = Path(__file__).parents[1]


@pytest.fixture
def gateway_server() -> Iterator[tuple[str, list[str]]]:
    """Serve one initial issue and no issues for validation run IDs."""

    requests: list[str] = []

    class GatewayHandler(BaseHTTPRequestHandler):
        """Return deterministic issue discovery and validation responses."""

        def do_GET(self) -> None:
            requests.append(self.path)
            query = parse_qs(urlparse(self.path).query)
            if self.path == "/diagnostics/issues/client:123":
                body = json.dumps(
                    {
                        "summary": {
                            "issue_id": "client:123",
                            "timestamp": "2026-06-01T08:30:00Z",
                            "service": "todo-flutter-macos",
                            "exception_type": "StateError",
                            "message": "todo completion failed",
                        },
                        "stacktrace": [{"function": "completeTodo"}],
                        "breadcrumbs": [{"category": "ui.tap"}],
                        "context": {"environment": "local"},
                        "trace_correlation": {
                            "trace_id": None,
                            "source": "sentry_trace_context",
                        },
                    }
                ).encode()
            else:
                value: list[dict[str, object]] = []
                if "run_id" not in query:
                    value = [
                        {
                            "issue_id": "client:123",
                            "timestamp": "2026-06-01T08:30:00Z",
                            "service": "todo-flutter-macos",
                            "exception_type": "StateError",
                            "message": "todo completion failed",
                        }
                    ]
                body = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            """Disable HTTP server log output during Coordinator tests."""

            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", requests
    server.shutdown()
    thread.join()


def test_process_next_repairs_validates_and_publishes_pull_request(
    gateway_server: tuple[str, list[str]], tmp_path: Path
) -> None:
    gateway_url, gateway_requests = gateway_server
    database_path = tmp_path / "repair-coordinator.db"
    repository_path = tmp_path / "repository"
    remote_path = tmp_path / "remote.git"
    worktree_root = tmp_path / "worktrees"
    workload_path = tmp_path / "validation.hs.yaml"
    toolkit_path = tmp_path / "fake-flutter-mcp-toolkit"
    toolkit_capture_path = tmp_path / "toolkit-invocations.jsonl"
    flutter_launcher_path = tmp_path / "fake-flutter-launcher"
    flutter_launch_capture_path = tmp_path / "flutter-launch.txt"
    codex_path = tmp_path / "fake-codex"
    gh_path = tmp_path / "fake-gh"
    initialize_git_repository(repository_path, remote_path)
    write_fake_codex(codex_path)
    write_fake_toolkit(toolkit_path)
    write_fake_flutter_launcher(flutter_launcher_path)
    write_fake_gh(gh_path)
    workload_path.write_text("version: 1\nname: validation_journey\nsteps: []\n")
    environment = {
        "REPAIR_COORDINATOR_DB_PATH": str(database_path),
        "DIAGNOSTICS_GATEWAY_URL": gateway_url,
        "REPAIR_REPOSITORY_ROOT": str(repository_path),
        "REPAIR_WORKTREE_ROOT": str(worktree_root),
        "REPAIR_CODEX_COMMAND": str(codex_path),
        "FLUTTER_MCP_TOOLKIT_COMMAND": str(toolkit_path),
        "FLUTTER_MCP_TOOLKIT_CAPTURE_PATH": str(toolkit_capture_path),
        "REPAIR_FLUTTER_LAUNCH_COMMAND": str(flutter_launcher_path),
        "REPAIR_FLUTTER_LAUNCH_CAPTURE_PATH": str(flutter_launch_capture_path),
        "REPAIR_GH_COMMAND": str(gh_path),
        "GIT_AUTHOR_NAME": "Repair Coordinator Test",
        "GIT_AUTHOR_EMAIL": "repair-coordinator@example.com",
        "GIT_COMMITTER_NAME": "Repair Coordinator Test",
        "GIT_COMMITTER_EMAIL": "repair-coordinator@example.com",
    }
    run_result = run_coordinator(
        "run",
        "--interval-seconds",
        "0",
        "--max-polls",
        "1",
        "--workload",
        str(workload_path),
        environment=environment,
    )
    result = run_result["processed"][0]
    toolkit_invocations = [
        json.loads(line) for line in toolkit_capture_path.read_text().splitlines()
    ]

    assert result["task_id"] == 1
    assert result["attempts"] == 1
    assert result["status"] == "pr_created"
    assert result["pr_url"] == "https://github.example.test/demo/pull/1"
    assert run_result["polls"] == 1
    assert run_result["created"] == 1
    assert [entry["name"] for entry in toolkit_invocations] == [
        "discover_debug_apps",
        "discover_debug_apps",
        "hot_restart_flutter",
        "fmt_client_tool",
    ]
    assert flutter_launch_capture_path.read_text() == str(worktree_root / "repair-1")
    assert any("run_id=" in request for request in gateway_requests)
    assert (
        subprocess.run(
            ["git", "ls-files", ".repair/evidence.json"],
            check=True,
            capture_output=True,
            cwd=worktree_root / "repair-1",
            text=True,
        ).stdout
        == ""
    )


def test_process_next_stops_after_three_disallowed_repair_attempts(
    gateway_server: tuple[str, list[str]], tmp_path: Path
) -> None:
    gateway_url, gateway_requests = gateway_server
    database_path = tmp_path / "repair-coordinator.db"
    repository_path = tmp_path / "repository"
    remote_path = tmp_path / "remote.git"
    worktree_root = tmp_path / "worktrees"
    workload_path = tmp_path / "validation.hs.yaml"
    toolkit_path = tmp_path / "fake-flutter-mcp-toolkit"
    toolkit_capture_path = tmp_path / "toolkit-invocations.jsonl"
    codex_path = tmp_path / "fake-codex"
    codex_capture_path = tmp_path / "codex-invocations.txt"
    initialize_git_repository(repository_path, remote_path)
    write_disallowed_fake_codex(codex_path)
    write_fake_toolkit(toolkit_path)
    workload_path.write_text("version: 1\nname: validation_journey\nsteps: []\n")
    environment = {
        "REPAIR_COORDINATOR_DB_PATH": str(database_path),
        "DIAGNOSTICS_GATEWAY_URL": gateway_url,
        "REPAIR_REPOSITORY_ROOT": str(repository_path),
        "REPAIR_WORKTREE_ROOT": str(worktree_root),
        "REPAIR_CODEX_COMMAND": str(codex_path),
        "REPAIR_CODEX_CAPTURE_PATH": str(codex_capture_path),
        "FLUTTER_MCP_TOOLKIT_COMMAND": str(toolkit_path),
        "FLUTTER_MCP_TOOLKIT_CAPTURE_PATH": str(toolkit_capture_path),
    }

    run_result = run_coordinator(
        "run",
        "--interval-seconds",
        "0",
        "--max-polls",
        "1",
        "--workload",
        str(workload_path),
        environment=environment,
    )
    result = run_result["processed"][0]

    assert result["status"] == "failed"
    assert result["attempts"] == 3
    assert len(result["attempt_history"]) == 3
    assert result["current_diff"]["disallowed_paths"] == ["harness/forbidden.txt"]
    assert codex_capture_path.read_text().splitlines() == [
        "dirty=False",
        "dirty=False",
        "dirty=False",
    ]
    assert gateway_requests.count("/diagnostics/issues/client:123") == 1
    assert not toolkit_capture_path.exists()


def run_coordinator(*arguments: str, environment: dict[str, str]) -> object:
    """Run one Coordinator CLI command and return its JSON response."""

    result = subprocess.run(
        [sys.executable, "-m", "repair_coordinator", *arguments],
        check=False,
        capture_output=True,
        cwd=SERVICE_ROOT,
        env={**os.environ, **environment},
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def initialize_git_repository(repository_path: Path, remote_path: Path) -> None:
    """Create one committed Git repository with a local bare remote."""

    repository_path.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"],
        check=True,
        capture_output=True,
        cwd=repository_path,
    )
    subprocess.run(
        ["git", "init", "--bare", str(remote_path)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote_path)],
        check=True,
        cwd=repository_path,
    )
    (repository_path / "app/lib").mkdir(parents=True)
    (repository_path / "app/lib/main.dart").write_text("// Todo app\n")
    subprocess.run(["git", "add", "."], check=True, cwd=repository_path)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Repair Coordinator Test",
            "-c",
            "user.email=repair-coordinator@example.com",
            "commit",
            "-m",
            "Initial commit",
        ],
        check=True,
        capture_output=True,
        cwd=repository_path,
    )


def write_fake_codex(codex_path: Path) -> None:
    """Write a Codex replacement that edits Flutter product code."""

    codex_path.write_text(
        """#!/usr/bin/env python3
from pathlib import Path

Path("app/lib/main.dart").write_text("// repaired by Codex\\n")
print("repair proposed")
"""
    )
    codex_path.chmod(0o755)


def write_fake_toolkit(toolkit_path: Path) -> None:
    """Write a Flutter MCP replacement that records restart and replay calls."""

    toolkit_path.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

if sys.argv[1:] != ["serve"]:
    raise SystemExit("expected serve mode")
capture_path = Path(os.environ["FLUTTER_MCP_TOOLKIT_CAPTURE_PATH"])
for line in sys.stdin:
    request = json.loads(line)
    if request["method"] == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": {}}), flush=True)
        continue
    name = request["params"]["name"]
    arguments = request["params"]["args"]
    with capture_path.open("a") as capture:
        capture.write(json.dumps({"name": name, "arguments": arguments}) + "\\n")
    data = {}
    if name == "discover_debug_apps":
        discoveries = [
            line
            for line in capture_path.read_text().splitlines()
            if json.loads(line)["name"] == "discover_debug_apps"
        ]
        target_id = "baseline" if len(discoveries) == 1 else "repair"
        data = {"count": 1, "targets": [{"targetId": target_id}]}
    print(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {"ok": True, "data": data, "error": None},
            }
        ),
        flush=True,
    )
"""
    )
    toolkit_path.chmod(0o755)


def write_fake_flutter_launcher(launcher_path: Path) -> None:
    """Write a Flutter launcher replacement that records its repair worktree."""

    launcher_path.write_text(
        """#!/usr/bin/env python3
import os
from pathlib import Path
import sys

Path(os.environ["REPAIR_FLUTTER_LAUNCH_CAPTURE_PATH"]).write_text(sys.argv[1])
"""
    )
    launcher_path.chmod(0o755)


def write_disallowed_fake_codex(codex_path: Path) -> None:
    """Write a Codex replacement that repeatedly edits one protected path."""

    codex_path.write_text(
        """#!/usr/bin/env python3
import os
from pathlib import Path

Path("harness").mkdir(exist_ok=True)
forbidden_path = Path("harness/forbidden.txt")
with Path(os.environ["REPAIR_CODEX_CAPTURE_PATH"]).open("a") as capture:
    capture.write(f"dirty={forbidden_path.exists()}\\n")
forbidden_path.write_text("not allowed\\n")
"""
    )
    codex_path.chmod(0o755)


def write_fake_gh(gh_path: Path) -> None:
    """Write a GitHub CLI replacement that returns one pull request URL."""

    gh_path.write_text(
        """#!/usr/bin/env python3
print("https://github.example.test/demo/pull/1")
"""
    )
    gh_path.chmod(0o755)
