import os
from pathlib import Path
import shlex
import subprocess
import time

from repair_coordinator.workloads import ToolkitClient


class ComponentRestarter:
    """Restart local components affected by whitelisted product-code changes."""

    def __init__(
        self,
        toolkit: ToolkitClient,
        docker_command: list[str],
        compose_project_name: str,
        compose_env_file: Path,
        flutter_launch_command: list[str] | None,
    ) -> None:
        self._toolkit = toolkit
        self._docker_command = docker_command
        self._compose_project_name = compose_project_name
        self._compose_env_file = compose_env_file
        self._flutter_launch_command = flutter_launch_command

    @classmethod
    def from_environment(
        cls, toolkit: ToolkitClient | None = None
    ) -> "ComponentRestarter":
        """Create a restarter from local toolkit and Docker configuration."""

        repository_root = Path(os.environ["REPAIR_REPOSITORY_ROOT"])
        return cls(
            toolkit or ToolkitClient.from_environment(),
            shlex.split(os.environ.get("REPAIR_DOCKER_COMMAND", "docker")),
            os.environ.get("REPAIR_COMPOSE_PROJECT_NAME", repository_root.name),
            Path(
                os.environ.get(
                    "REPAIR_COMPOSE_ENV_FILE",
                    str(repository_root / ".env"),
                )
            ),
            shlex.split(os.environ["REPAIR_FLUTTER_LAUNCH_COMMAND"])
            if "REPAIR_FLUTTER_LAUNCH_COMMAND" in os.environ
            else None,
        )

    def restart(self, task: dict[str, object], changed_paths: list[str]) -> None:
        """Restart only the Flutter App or Todo API changed by one repair."""

        if any(path.startswith("services/todo_api/") for path in changed_paths):
            subprocess.run(
                [
                    *self._docker_command,
                    "compose",
                    "--project-name",
                    self._compose_project_name,
                    "--env-file",
                    str(self._compose_env_file),
                    "up",
                    "-d",
                    "--build",
                    "--no-deps",
                    "todo-api",
                ],
                check=True,
                cwd=str(task["worktree_path"]),
            )
        if any(path.startswith("app/lib/") for path in changed_paths):
            if self._flutter_launch_command is None:
                raise ValueError(
                    "Flutter repair validation requires REPAIR_FLUTTER_LAUNCH_COMMAND"
                )
            previous_target_ids = self._discover_target_ids()
            subprocess.Popen(
                [*self._flutter_launch_command, str(task["worktree_path"])],
                cwd=str(task["worktree_path"]),
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._wait_for_flutter_target(previous_target_ids)
            self._toolkit.execute("hot_restart_flutter", {})

    def _wait_for_flutter_target(self, previous_target_ids: set[str]) -> None:
        """Wait until the toolkit discovers the relaunched Flutter debug App."""

        for _ in range(60):
            if self._discover_target_ids() - previous_target_ids:
                return
            time.sleep(0.5)
        raise TimeoutError("Flutter debug App was not discoverable after relaunch")

    def _discover_target_ids(self) -> set[str]:
        """Return Flutter debug target IDs currently visible to the toolkit."""

        result = self._toolkit.execute("discover_debug_apps", {})
        return {
            str(target["targetId"])
            for target in result.get("targets", [])
            if "targetId" in target
        }
