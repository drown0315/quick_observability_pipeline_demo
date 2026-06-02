import json
import os
from pathlib import Path

from repair_coordinator.restart import ComponentRestarter


def test_restart_todo_api_uses_repository_env_file(tmp_path: Path) -> None:
    repository_path = tmp_path / "repository"
    worktree_path = tmp_path / "worktree"
    docker_path = tmp_path / "fake-docker"
    capture_path = tmp_path / "docker-invocation.json"
    repository_path.mkdir()
    worktree_path.mkdir()
    write_fake_docker(docker_path)

    previous_environment = os.environ.copy()
    try:
        os.environ.update(
            {
                "REPAIR_REPOSITORY_ROOT": str(repository_path),
                "REPAIR_DOCKER_COMMAND": str(docker_path),
                "REPAIR_DOCKER_CAPTURE_PATH": str(capture_path),
            }
        )
        ComponentRestarter.from_environment().restart(
            {"worktree_path": str(worktree_path)},
            ["services/todo_api/todo_api/main.py"],
        )
    finally:
        os.environ.clear()
        os.environ.update(previous_environment)

    invocation = json.loads(capture_path.read_text())
    assert invocation == {
        "arguments": [
            "compose",
            "--project-name",
            "repository",
            "--env-file",
            str(repository_path / ".env"),
            "up",
            "-d",
            "--build",
            "--no-deps",
            "todo-api",
        ],
        "cwd": str(worktree_path),
    }


def write_fake_docker(docker_path: Path) -> None:
    """Write a Docker replacement that records its arguments and working directory."""

    docker_path.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

Path(os.environ["REPAIR_DOCKER_CAPTURE_PATH"]).write_text(
    json.dumps({"arguments": sys.argv[1:], "cwd": os.getcwd()})
)
"""
    )
    docker_path.chmod(0o755)
