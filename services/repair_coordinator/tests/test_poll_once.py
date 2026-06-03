import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
from threading import Thread
from typing import Iterator

import pytest

from repair_coordinator.__main__ import build_parser
from repair_coordinator.codex import CodexRunner

SERVICE_ROOT = Path(__file__).parents[1]


def test_verbose_flag_is_available_for_codex_running_commands() -> None:
    parser = build_parser()

    assert parser.parse_args(["run", "--verbose"]).verbose is True
    assert (
        parser.parse_args(
            ["process-next", "--workload", "journey.yaml", "--verbose"]
        ).verbose
        is True
    )
    assert (
        parser.parse_args(["invoke-codex", "1", "--attempt", "1", "--verbose"]).verbose
        is True
    )


@pytest.fixture
def gateway_url() -> Iterator[str]:
    """Serve one client issue through the Gateway list interface."""

    class GatewayHandler(BaseHTTPRequestHandler):
        """Return one deterministic client issue for every poll."""

        def do_GET(self) -> None:
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
                assert self.path == "/diagnostics/issues?since=15m&limit=20"
                body = json.dumps(
                    [
                        {
                            "issue_id": "client:123",
                            "timestamp": "2026-06-01T08:30:00Z",
                            "service": "todo-flutter-macos",
                            "exception_type": "StateError",
                            "message": "todo completion failed",
                        }
                    ]
                ).encode()
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
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join()


def test_poll_once_creates_one_task_for_repeated_issue(
    gateway_url: str, tmp_path: Path
) -> None:
    database_path = tmp_path / "repair-coordinator.db"

    first_poll = run_coordinator(
        "poll-once", gateway_url=gateway_url, database_path=database_path
    )
    second_poll = run_coordinator(
        "poll-once", gateway_url=gateway_url, database_path=database_path
    )
    listed_tasks = run_coordinator(
        "list-tasks", gateway_url=gateway_url, database_path=database_path
    )

    assert first_poll == {"created": 1, "seen": 1}
    assert second_poll == {"created": 0, "seen": 1}
    assert listed_tasks == [
        {
            "issue_id": "client:123",
            "status": "queued",
        }
    ]


def test_run_reuses_deduplicated_polling_for_each_interval(
    gateway_url: str, tmp_path: Path
) -> None:
    database_path = tmp_path / "repair-coordinator.db"

    result = run_coordinator(
        "run",
        "--interval-seconds",
        "0",
        "--max-polls",
        "2",
        gateway_url=gateway_url,
        database_path=database_path,
    )
    listed_tasks = run_coordinator(
        "list-tasks", gateway_url=gateway_url, database_path=database_path
    )

    assert result == {"polls": 2, "created": 1, "seen": 2}
    assert listed_tasks == [
        {
            "issue_id": "client:123",
            "status": "queued",
        }
    ]


def test_claim_next_returns_each_queued_task_once(
    gateway_url: str, tmp_path: Path
) -> None:
    database_path = tmp_path / "repair-coordinator.db"
    run_coordinator(
        "poll-once", gateway_url=gateway_url, database_path=database_path
    )

    claimed_task = run_coordinator(
        "claim-next", gateway_url=gateway_url, database_path=database_path
    )
    no_task = run_coordinator(
        "claim-next", gateway_url=gateway_url, database_path=database_path
    )
    listed_tasks = run_coordinator(
        "list-tasks", gateway_url=gateway_url, database_path=database_path
    )

    assert claimed_task == {
        "task_id": 1,
        "issue_id": "client:123",
        "status": "running",
    }
    assert no_task is None
    assert listed_tasks == [
        {
            "issue_id": "client:123",
            "status": "running",
        }
    ]


def test_prepare_worktree_creates_isolated_repair_branch(
    gateway_url: str, tmp_path: Path
) -> None:
    database_path = tmp_path / "repair-coordinator.db"
    repository_path = tmp_path / "repository"
    worktree_root = tmp_path / "worktrees"
    initialize_git_repository(repository_path)
    run_coordinator(
        "poll-once", gateway_url=gateway_url, database_path=database_path
    )
    run_coordinator(
        "claim-next", gateway_url=gateway_url, database_path=database_path
    )

    prepared = run_coordinator(
        "prepare-worktree",
        "1",
        gateway_url=gateway_url,
        database_path=database_path,
        extra_environment={
            "REPAIR_REPOSITORY_ROOT": str(repository_path),
            "REPAIR_WORKTREE_ROOT": str(worktree_root),
        },
    )

    assert prepared == {
        "task_id": 1,
        "branch": "codex/repair-1",
        "worktree_path": str(worktree_root / "repair-1"),
    }
    assert (
        subprocess.run(
            ["git", "branch", "--show-current"],
            check=True,
            capture_output=True,
            cwd=worktree_root / "repair-1",
            text=True,
        ).stdout.strip()
        == "codex/repair-1"
    )


def test_prepare_worktree_uses_suffix_when_repair_branch_exists(
    gateway_url: str, tmp_path: Path
) -> None:
    database_path = tmp_path / "repair-coordinator.db"
    repository_path = tmp_path / "repository"
    worktree_root = tmp_path / "worktrees"
    initialize_git_repository(repository_path)
    subprocess.run(
        ["git", "branch", "codex/repair-1"],
        check=True,
        cwd=repository_path,
    )
    run_coordinator(
        "poll-once", gateway_url=gateway_url, database_path=database_path
    )
    run_coordinator(
        "claim-next", gateway_url=gateway_url, database_path=database_path
    )

    prepared = run_coordinator(
        "prepare-worktree",
        "1",
        gateway_url=gateway_url,
        database_path=database_path,
        extra_environment={
            "REPAIR_REPOSITORY_ROOT": str(repository_path),
            "REPAIR_WORKTREE_ROOT": str(worktree_root),
        },
    )

    assert prepared == {
        "task_id": 1,
        "branch": "codex/repair-1-2",
        "worktree_path": str(worktree_root / "repair-1-2"),
    }


def test_invoke_codex_runs_repair_prompt_for_prepared_task(
    gateway_url: str, tmp_path: Path
) -> None:
    database_path = tmp_path / "repair-coordinator.db"
    repository_path = tmp_path / "repository"
    worktree_root = tmp_path / "worktrees"
    capture_path = tmp_path / "codex-invocation.json"
    codex_path = tmp_path / "fake-codex"
    initialize_git_repository(repository_path)
    (repository_path / ".env").write_text(
        "SENTRY_AUTH_TOKEN=test-token\n"
        "SENTRY_ORG=test-org\n"
        "SENTRY_PROJECT=todo-flutter-macos\n"
    )
    write_fake_codex(codex_path)
    environment = {
        "REPAIR_REPOSITORY_ROOT": str(repository_path),
        "REPAIR_WORKTREE_ROOT": str(worktree_root),
        "REPAIR_COMPOSE_ENV_FILE": str(repository_path / ".env"),
        "REPAIR_CODEX_COMMAND": str(codex_path),
        "REPAIR_CODEX_CAPTURE_PATH": str(capture_path),
    }
    run_coordinator(
        "poll-once", gateway_url=gateway_url, database_path=database_path
    )
    run_coordinator(
        "claim-next", gateway_url=gateway_url, database_path=database_path
    )
    run_coordinator(
        "prepare-worktree",
        "1",
        gateway_url=gateway_url,
        database_path=database_path,
        extra_environment=environment,
    )

    result = run_coordinator(
        "invoke-codex",
        "1",
        "--attempt",
        "1",
        gateway_url=gateway_url,
        database_path=database_path,
        extra_environment=environment,
    )
    invocation = json.loads(capture_path.read_text())

    assert result == {
        "task_id": 1,
        "attempt": 1,
        "returncode": 0,
        "output": "repair proposed\n",
        "error_output": "",
    }
    assert invocation["arguments"][:7] == [
        "--ask-for-approval",
        "never",
        "exec",
        "-C",
        str(worktree_root / "repair-1"),
        "--sandbox",
        "workspace-write",
    ]
    prompt = invocation["arguments"][7]
    assert "client:123" in prompt
    assert ".repair/evidence.json" in prompt
    assert "app/lib/" in prompt
    assert "services/todo_api/" in prompt
    assert "harness/" in prompt
    assert "REPAIR_COMPOSE_ENV_FILE" in prompt
    assert "docker compose" in prompt
    assert invocation["environment"] == {
        "REPAIR_COMPOSE_ENV_FILE": str(repository_path / ".env"),
        "SENTRY_AUTH_TOKEN": "test-token",
        "SENTRY_ORG": "test-org",
        "SENTRY_PROJECT": "todo-flutter-macos",
    }
    snapshot = json.loads((worktree_root / "repair-1/.repair/evidence.json").read_text())
    assert snapshot["issue_id"] == "client:123"
    assert snapshot["source"] == "diagnostics_gateway"
    assert snapshot["detail"]["summary"]["message"] == "todo completion failed"


def test_invoke_codex_uses_configured_sandbox(
    gateway_url: str, tmp_path: Path
) -> None:
    database_path = tmp_path / "repair-coordinator.db"
    repository_path = tmp_path / "repository"
    worktree_root = tmp_path / "worktrees"
    capture_path = tmp_path / "codex-invocation.json"
    codex_path = tmp_path / "fake-codex"
    initialize_git_repository(repository_path)
    write_fake_codex(codex_path)
    environment = {
        "REPAIR_REPOSITORY_ROOT": str(repository_path),
        "REPAIR_WORKTREE_ROOT": str(worktree_root),
        "REPAIR_CODEX_COMMAND": str(codex_path),
        "REPAIR_CODEX_CAPTURE_PATH": str(capture_path),
        "REPAIR_CODEX_SANDBOX": "danger-full-access",
    }
    run_coordinator(
        "poll-once", gateway_url=gateway_url, database_path=database_path
    )
    run_coordinator(
        "claim-next", gateway_url=gateway_url, database_path=database_path
    )
    run_coordinator(
        "prepare-worktree",
        "1",
        gateway_url=gateway_url,
        database_path=database_path,
        extra_environment=environment,
    )

    run_coordinator(
        "invoke-codex",
        "1",
        "--attempt",
        "1",
        gateway_url=gateway_url,
        database_path=database_path,
        extra_environment=environment,
    )
    invocation = json.loads(capture_path.read_text())

    sandbox_index = invocation["arguments"].index("--sandbox")
    assert invocation["arguments"][sandbox_index + 1] == "danger-full-access"


def test_verbose_codex_invocation_streams_and_retains_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    codex_path = tmp_path / "fake-codex"
    write_verbose_fake_codex(codex_path)

    result = CodexRunner([str(codex_path)], verbose=True).invoke(
        {
            "task_id": 1,
            "issue_id": "client:123",
            "status": "running",
            "worktree_path": str(tmp_path),
        },
        attempt=1,
    )
    captured = capsys.readouterr()

    assert captured.out == "repair stdout\n"
    assert captured.err == "repair stderr\n"
    assert result["output"] == "repair stdout\n"
    assert result["error_output"] == "repair stderr\n"


def test_check_changes_rejects_protected_paths(
    gateway_url: str, tmp_path: Path
) -> None:
    database_path = tmp_path / "repair-coordinator.db"
    repository_path = tmp_path / "repository"
    worktree_root = tmp_path / "worktrees"
    initialize_git_repository(repository_path)
    environment = {
        "REPAIR_REPOSITORY_ROOT": str(repository_path),
        "REPAIR_WORKTREE_ROOT": str(worktree_root),
    }
    run_coordinator(
        "poll-once", gateway_url=gateway_url, database_path=database_path
    )
    run_coordinator(
        "claim-next", gateway_url=gateway_url, database_path=database_path
    )
    run_coordinator(
        "prepare-worktree",
        "1",
        gateway_url=gateway_url,
        database_path=database_path,
        extra_environment=environment,
    )
    repair_worktree = worktree_root / "repair-1"
    (repair_worktree / "app/lib/main.dart").write_text("// repaired\n")
    (repair_worktree / "harness/journey.hs.yaml").write_text("changed: true\n")

    result = run_coordinator(
        "check-changes",
        "1",
        gateway_url=gateway_url,
        database_path=database_path,
        extra_environment=environment,
    )

    assert result == {
        "valid": False,
        "changed_paths": [
            "app/lib/main.dart",
            "harness/journey.hs.yaml",
        ],
        "disallowed_paths": ["harness/journey.hs.yaml"],
    }


def test_publish_pr_pushes_validated_repair_as_normal_pull_request(
    gateway_url: str, tmp_path: Path
) -> None:
    database_path = tmp_path / "repair-coordinator.db"
    repository_path = tmp_path / "repository"
    remote_path = tmp_path / "remote.git"
    worktree_root = tmp_path / "worktrees"
    validation_path = tmp_path / "validation.json"
    gh_path = tmp_path / "fake-gh"
    gh_capture_path = tmp_path / "gh-invocation.json"
    initialize_git_repository(repository_path, remote_path=remote_path)
    write_fake_gh(gh_path)
    validation_path.write_text(
        json.dumps(
            {
                "name": "mixed_user_workload",
                "run_id": "00000000-0000-0000-0000-000000000456",
                "status": "passed",
                "completed_steps": 20,
            }
        )
    )
    environment = {
        "REPAIR_REPOSITORY_ROOT": str(repository_path),
        "REPAIR_WORKTREE_ROOT": str(worktree_root),
        "REPAIR_GH_COMMAND": str(gh_path),
        "REPAIR_GH_CAPTURE_PATH": str(gh_capture_path),
        "GIT_AUTHOR_NAME": "Repair Coordinator Test",
        "GIT_AUTHOR_EMAIL": "repair-coordinator@example.com",
        "GIT_COMMITTER_NAME": "Repair Coordinator Test",
        "GIT_COMMITTER_EMAIL": "repair-coordinator@example.com",
    }
    run_coordinator(
        "poll-once", gateway_url=gateway_url, database_path=database_path
    )
    run_coordinator(
        "claim-next", gateway_url=gateway_url, database_path=database_path
    )
    run_coordinator(
        "prepare-worktree",
        "1",
        gateway_url=gateway_url,
        database_path=database_path,
        extra_environment=environment,
    )
    repair_worktree = worktree_root / "repair-1"
    (repair_worktree / "app/lib/main.dart").write_text("// repaired\n")

    result = run_coordinator(
        "publish-pr",
        "1",
        "--validation-report",
        str(validation_path),
        gateway_url=gateway_url,
        database_path=database_path,
        extra_environment=environment,
    )
    gh_invocation = json.loads(gh_capture_path.read_text())

    assert result == {
        "task_id": 1,
        "status": "pr_created",
        "pr_url": "https://github.example.test/demo/pull/1",
    }
    assert gh_invocation["arguments"][:2] == ["pr", "create"]
    assert "--draft" not in gh_invocation["arguments"]
    assert (
        subprocess.run(
            [
                "git",
                "--git-dir",
                str(remote_path),
                "branch",
                "--list",
                "codex/repair-1",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == "codex/repair-1"
    )


def run_coordinator(
    *arguments: str,
    gateway_url: str,
    database_path: Path,
    extra_environment: dict[str, str] | None = None,
) -> object:
    """Run one Coordinator CLI command and return its JSON response.

    Args:
        arguments: Public Coordinator command and its options. The tracer tests
            use `poll-once` or `run` to discover issues and `list-tasks` to
            inspect queued work.
        gateway_url: Temporary Gateway base URL queried by `poll-once`.
        database_path: SQLite path shared by CLI calls in one test.
        extra_environment: Optional command-specific environment values.

    Returns:
        JSON value printed by the Coordinator command.

    Example:
        `run_coordinator("poll-once", gateway_url=url, database_path=path)`
        returns `{"seen": 1, "created": 1}` for one new issue.
    """

    result = subprocess.run(
        [sys.executable, "-m", "repair_coordinator", *arguments],
        check=False,
        capture_output=True,
        cwd=SERVICE_ROOT,
        env={
            **os.environ,
            "REPAIR_COORDINATOR_DB_PATH": str(database_path),
            "DIAGNOSTICS_GATEWAY_URL": gateway_url,
            **(extra_environment or {}),
        },
        text=True,
    )

    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def initialize_git_repository(
    repository_path: Path, *, remote_path: Path | None = None
) -> None:
    """Create one committed Git repository for worktree behavior tests."""

    repository_path.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"],
        check=True,
        capture_output=True,
        cwd=repository_path,
        text=True,
    )
    if remote_path is not None:
        subprocess.run(
            ["git", "init", "--bare", str(remote_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "remote", "add", "origin", str(remote_path)],
            check=True,
            cwd=repository_path,
        )
    (repository_path / "app/lib").mkdir(parents=True)
    (repository_path / "harness").mkdir()
    (repository_path / "README.md").write_text("# Test repository\n")
    (repository_path / "app/lib/main.dart").write_text("// Todo app\n")
    (repository_path / "harness/journey.hs.yaml").write_text("version: 1\n")
    subprocess.run(
        ["git", "add", "."],
        check=True,
        cwd=repository_path,
    )
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
        text=True,
    )


def write_fake_codex(codex_path: Path) -> None:
    """Write a deterministic Codex replacement that records its arguments."""

    codex_path.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

Path(os.environ["REPAIR_CODEX_CAPTURE_PATH"]).write_text(
    json.dumps(
        {
            "arguments": sys.argv[1:],
            "environment": {
                name: os.environ.get(name)
                for name in (
                    "REPAIR_COMPOSE_ENV_FILE",
                    "SENTRY_AUTH_TOKEN",
                    "SENTRY_ORG",
                    "SENTRY_PROJECT",
                )
            },
        }
    )
)
print("repair proposed")
"""
    )
    codex_path.chmod(0o755)


def write_verbose_fake_codex(codex_path: Path) -> None:
    """Write a Codex replacement that emits one stdout and stderr line."""

    codex_path.write_text(
        """#!/usr/bin/env python3
import sys

print("repair stdout", flush=True)
print("repair stderr", file=sys.stderr, flush=True)
"""
    )
    codex_path.chmod(0o755)


def write_fake_gh(gh_path: Path) -> None:
    """Write a deterministic GitHub CLI replacement that records its arguments."""

    gh_path.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

Path(os.environ["REPAIR_GH_CAPTURE_PATH"]).write_text(
    json.dumps({"arguments": sys.argv[1:]})
)
print("https://github.example.test/demo/pull/1")
"""
    )
    gh_path.chmod(0o755)
