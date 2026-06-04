import os
from pathlib import Path
import shlex
import subprocess
from typing import Callable


class FlutterValidator:
    """Run host-side Flutter checks for one repaired app worktree."""

    def __init__(
        self,
        commands: list[list[str]],
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self._commands = commands
        self._progress = progress

    @classmethod
    def from_environment(
        cls, progress: Callable[[str], None] | None = None
    ) -> "FlutterValidator":
        """Create a validator from local Flutter command configuration."""

        return cls(
            [
                shlex.split(
                    os.environ.get("REPAIR_FLUTTER_TEST_COMMAND", "flutter test")
                ),
                shlex.split(
                    os.environ.get("REPAIR_FLUTTER_ANALYZE_COMMAND", "flutter analyze")
                ),
                shlex.split(
                    os.environ.get(
                        "REPAIR_FLUTTER_BUILD_COMMAND",
                        "flutter build macos --debug",
                    )
                ),
            ],
            progress=progress,
        )

    def validate(
        self, task: dict[str, object], changed_paths: list[str]
    ) -> list[dict[str, object]]:
        """Run Flutter checks when a repair changed app product code."""

        if not any(path.startswith("app/lib/") for path in changed_paths):
            return []

        app_path = Path(str(task["worktree_path"])) / "app"
        results: list[dict[str, object]] = []
        for command in self._commands:
            self._report(f"running {' '.join(command)}")
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                cwd=app_path,
                text=True,
            )
            results.append(
                {
                    "command": command,
                    "returncode": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                }
            )
        return results

    def _report(self, message: str) -> None:
        if self._progress is not None:
            self._progress(message)
