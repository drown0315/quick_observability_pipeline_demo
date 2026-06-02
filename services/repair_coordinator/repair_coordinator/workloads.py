import json
import os
from pathlib import Path
import shlex
from string import Template
import subprocess
from datetime import datetime, timezone
from typing import Callable

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


class ToolkitProcessError(Exception):
    """Failure to exchange JSON-RPC messages with the toolkit daemon."""


class ToolkitClient:
    """Run Flutter MCP toolkit commands and return their data payloads.

    The client contains the local `flutter-mcp-toolkit` command and one daemon
    process. Calls share the daemon's Flutter VM connection so a workload can
    execute several UI actions without reconnecting between steps.

    Example:
        Executing `semantic_snapshot` returns its snapshot ID and semantic
        nodes.
    """

    def __init__(self, command: list[str]) -> None:
        self._command = command
        self._process: subprocess.Popen[str] | None = None
        self._next_request_id = 1

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

        for attempt in range(2):
            try:
                envelope = self._request(
                    "command/execute",
                    {"name": name, "args": arguments},
                )
                break
            except ToolkitProcessError as error:
                self.close()
                if attempt == 1:
                    raise ToolkitCommandError(
                        {
                            "code": "toolkit_process_failed",
                            "message": str(error),
                        }
                    ) from error
        if not envelope.get("ok"):
            raise ToolkitCommandError(envelope["error"])
        return envelope["data"]

    def close(self) -> None:
        """Stop the toolkit daemon when this client no longer needs its VM connection."""

        if self._process is None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
        self._process = None

    def _request(self, method: str, params: dict[str, object]) -> dict[str, object]:
        """Send one JSON-RPC request to the shared toolkit daemon."""

        if self._process is None:
            self._start()
        return self._send_request(method, params)

    def _start(self) -> None:
        """Start and initialize one toolkit daemon."""

        self._process = subprocess.Popen(
            [*self._command, "serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self._send_request("initialize", {})

    def _send_request(
        self, method: str, params: dict[str, object]
    ) -> dict[str, object]:
        """Write one request and return its JSON-RPC result object."""

        if (
            self._process is None
            or self._process.stdin is None
            or self._process.stdout is None
        ):
            raise ToolkitProcessError("toolkit daemon is not running")
        request_id = self._next_request_id
        self._next_request_id += 1
        try:
            self._process.stdin.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": method,
                        "params": params,
                    }
                )
                + "\n"
            )
            self._process.stdin.flush()
            line = self._process.stdout.readline()
        except (BrokenPipeError, OSError) as error:
            raise ToolkitProcessError(
                "toolkit daemon stopped while sending a request"
            ) from error
        if not line:
            raise ToolkitProcessError("toolkit daemon stopped before replying")
        try:
            response = json.loads(line)
        except json.JSONDecodeError as error:
            raise ToolkitProcessError("toolkit daemon returned invalid JSON") from error
        if "error" in response:
            raise ToolkitCommandError(response["error"])
        return response["result"]


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
    def from_environment(cls, toolkit: ToolkitClient | None = None) -> "WorkloadRunner":
        """Create a workload runner using the configured Flutter MCP CLI."""

        return cls(toolkit or ToolkitClient.from_environment(), SelectorResolver())

    def run(
        self,
        workload_path: Path,
        *,
        run_id: str,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, object]:
        """Replay one workload with a fresh UUID and report completed steps."""

        try:
            return self._run(workload_path, run_id=run_id, progress=progress)
        finally:
            self._toolkit.close()

    def _run(
        self,
        workload_path: Path,
        *,
        run_id: str,
        progress: Callable[[str], None] | None,
    ) -> dict[str, object]:
        """Replay one workload while its toolkit daemon remains connected."""

        workload = yaml.safe_load(workload_path.read_text())
        steps = workload["steps"]
        self._report(
            progress,
            f"workload {workload['name']} starting with {len(steps)} steps "
            f"(run_id={run_id})",
        )
        variables = self._variables(workload.get("variables", {}), run_id=run_id)
        self._report(progress, "setting Flutter workload run id")
        self._toolkit.execute(
            "fmt_client_tool",
            {
                "toolName": "todo_set_workload_run_id",
                "arguments": {"run_id": run_id},
            },
        )
        completed_steps = 0
        for index, raw_step in enumerate(steps):
            step = self._expand(raw_step, variables)
            self._report(
                progress,
                f"step {index + 1}/{len(steps)}: {self._describe_step(step)}",
            )
            try:
                self._run_step(step)
            except (SelectorResolutionError, ToolkitCommandError) as error:
                self._report(
                    progress,
                    f"step {index + 1}/{len(steps)} failed: {error}",
                )
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
            self._report(
                progress,
                f"step {index + 1}/{len(steps)} completed",
            )
        self._report(progress, f"workload {workload['name']} passed")
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

    @staticmethod
    def _describe_step(step: dict[str, object]) -> str:
        action = str(step["action"])
        if action == "wait_for":
            predicate = step["predicate"]
            return f"wait_for {predicate}"
        selector = step["selector"]
        if action == "enter_text":
            return f"enter_text into {selector}"
        if action == "tap":
            return f"tap {selector}"
        return action

    @staticmethod
    def _report(progress: Callable[[str], None] | None, message: str) -> None:
        if progress is not None:
            progress(message)
