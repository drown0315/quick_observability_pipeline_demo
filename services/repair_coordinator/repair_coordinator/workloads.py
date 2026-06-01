import json
import os
from pathlib import Path
import shlex
from string import Template
import subprocess
from datetime import datetime, timezone

import yaml


class SelectorResolutionError(Exception):
    """Failure to resolve one YAML selector to exactly one semantic widget."""

    def __init__(
        self,
        code: str,
        selector: dict[str, str],
        candidates: list[dict[str, object]],
    ) -> None:
        super().__init__(code)
        self.result = {
            "code": code,
            "selector": selector,
            "candidates": [
                {
                    "ref": candidate.get("ref"),
                    "label": candidate.get("label"),
                    "type": candidate.get("type"),
                }
                for candidate in candidates
            ],
        }


class ToolkitCommandError(Exception):
    """Structured failure returned by one Flutter MCP toolkit command."""

    def __init__(self, error: dict[str, object]) -> None:
        code = str(error.get("code", "toolkit_error"))
        message = str(error.get("message", "Flutter MCP toolkit command failed"))
        super().__init__(f"{code}: {message}")
        self.result = error


class ToolkitClient:
    """Run Flutter MCP toolkit commands and return their data payloads.

    The client contains the local `flutter-mcp-toolkit` command. Each call uses
    the CLI `exec` interface so workload replay drives the running Flutter App
    through the same MCP tools available to Codex.

    Example:
        Executing `semantic_snapshot` returns its snapshot ID and semantic
        nodes.
    """

    def __init__(self, command: list[str]) -> None:
        self._command = command

    @classmethod
    def from_environment(cls) -> "ToolkitClient":
        """Create a toolkit client from local Coordinator configuration."""

        return cls(
            shlex.split(
                os.environ.get("FLUTTER_MCP_TOOLKIT_COMMAND", "flutter-mcp-toolkit")
            )
        )

    def execute(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        """Execute one Flutter MCP command and return its data payload."""

        result = subprocess.run(
            [
                *self._command,
                "exec",
                "--name",
                name,
                "--args",
                json.dumps(arguments),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ToolkitCommandError(
                {
                    "code": "toolkit_process_failed",
                    "message": result.stderr.strip(),
                }
            )
        envelope = json.loads(result.stdout)
        if not envelope.get("ok"):
            raise ToolkitCommandError(envelope["error"])
        return envelope["data"]


class SelectorResolver:
    """Resolve strict YAML selectors against one Flutter semantic snapshot.

    A selector matches an exact label and widget type. Resolution succeeds only
    when exactly one semantic node matches, so replay never guesses between
    widgets or falls back to coordinates.

    Example:
        Resolving `textField` label `New Todo` returns the unique editable
        semantic node and its snapshot ID.
    """

    def resolve(
        self, snapshot: dict[str, object], selector: dict[str, str]
    ) -> dict[str, object]:
        """Return the unique semantic widget matching one YAML selector."""

        matches = [
            node
            for node in snapshot["nodes"]
            if node.get("label") == selector["label"]
            and self._matches_type(node, selector["type"])
        ]
        if not matches:
            raise SelectorResolutionError(
                "selector_not_found", selector, candidates=[]
            )
        if len(matches) > 1:
            raise SelectorResolutionError(
                "selector_ambiguous", selector, candidates=matches
            )
        snapshot_id = snapshot.get("snapshot_id", snapshot.get("snapshotId"))
        if snapshot_id is None:
            raise ValueError("semantic snapshot is missing its snapshot ID")
        return {
            "ref": matches[0]["ref"],
            "snapshotId": snapshot_id,
        }

    @staticmethod
    def _matches_type(node: dict[str, object], widget_type: str) -> bool:
        """Return whether one semantic node satisfies a YAML widget type."""

        if node.get("type") == widget_type:
            return True
        actions = node.get("actions", [])
        flags = node.get("flags", [])
        if widget_type == "textField":
            return "setText" in actions
        if widget_type == "button":
            return "tap" in actions and "isButton" in flags
        if widget_type == "checkbox":
            return "tap" in actions and "hasCheckedState" in flags
        raise ValueError(f"unsupported selector type: {widget_type}")


class WorkloadRunner:
    """Strictly replay reviewed YAML workloads through Flutter MCP commands.

    The runner expands workload variables from one UUID, stores that UUID in
    the Flutter App, and executes each reviewed UI step in order. Interactive
    selectors must resolve to one semantic widget.

    Example:
        Running `normal_todo_journey.hs.yaml` with one UUID replays its Todo UI
        actions without bypassing the App.
    """

    def __init__(
        self, toolkit: ToolkitClient, selector_resolver: SelectorResolver
    ) -> None:
        self._toolkit = toolkit
        self._selector_resolver = selector_resolver
        self._last_snapshot: dict[str, object] | None = None

    @classmethod
    def from_environment(cls) -> "WorkloadRunner":
        """Create a workload runner using the configured Flutter MCP CLI."""

        return cls(ToolkitClient.from_environment(), SelectorResolver())

    def run(self, workload_path: Path, *, run_id: str) -> dict[str, object]:
        """Replay one workload with a fresh UUID and report completed steps."""

        workload = yaml.safe_load(workload_path.read_text())
        variables = self._variables(workload.get("variables", {}), run_id=run_id)
        self._toolkit.execute(
            "fmt_client_tool",
            {
                "toolName": "todo_set_workload_run_id",
                "arguments": {"run_id": run_id},
            },
        )
        completed_steps = 0
        for index, raw_step in enumerate(workload["steps"]):
            step = self._expand(raw_step, variables)
            try:
                self._run_step(step)
            except (SelectorResolutionError, ToolkitCommandError) as error:
                return {
                    "name": workload["name"],
                    "run_id": run_id,
                    "status": "failed",
                    "completed_steps": completed_steps,
                    "failed_step": index,
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                    "error": error.result,
                    "last_snapshot": self._last_snapshot_or_none(),
                    "app_errors": self._app_errors_or_none(),
                }
            completed_steps += 1
        return {
            "name": workload["name"],
            "run_id": run_id,
            "status": "passed",
            "completed_steps": completed_steps,
        }

    def _run_step(self, step: dict[str, object]) -> None:
        """Execute one expanded workload step."""

        if step["action"] == "wait_for":
            self._toolkit.execute("wait_for", {"predicate": step["predicate"]})
            return

        snapshot = self._toolkit.execute("semantic_snapshot", {})
        self._last_snapshot = snapshot
        widget = self._selector_resolver.resolve(snapshot, step["selector"])
        if step["action"] == "enter_text":
            self._toolkit.execute(
                "enter_text",
                {**widget, "text": step["text"]},
            )
            return
        if step["action"] == "tap":
            self._toolkit.execute("tap_widget", widget)
            return
        raise ValueError(f"unsupported workload action: {step['action']}")

    def _last_snapshot_or_none(self) -> dict[str, object] | None:
        """Return the latest semantic snapshot when the App remains reachable."""

        if self._last_snapshot is not None:
            return self._last_snapshot
        try:
            self._last_snapshot = self._toolkit.execute("semantic_snapshot", {})
        except ToolkitCommandError:
            return None
        return self._last_snapshot

    def _app_errors_or_none(self) -> dict[str, object] | None:
        """Return recent Flutter App errors when the toolkit can still read them."""

        try:
            return self._toolkit.execute("get_app_errors", {})
        except ToolkitCommandError:
            return None

    @classmethod
    def _variables(cls, raw_variables: dict[str, str], *, run_id: str) -> dict[str, str]:
        """Expand workload variables from the Coordinator-generated run UUID."""

        variables = {"run_id": run_id}
        for name, value in raw_variables.items():
            variables[name] = Template(value).substitute(variables)
        return variables

    @classmethod
    def _expand(cls, value: object, variables: dict[str, str]) -> object:
        """Substitute workload variables inside nested YAML values."""

        if isinstance(value, str):
            return Template(value).substitute(variables)
        if isinstance(value, list):
            return [cls._expand(item, variables) for item in value]
        if isinstance(value, dict):
            return {key: cls._expand(item, variables) for key, item in value.items()}
        return value
