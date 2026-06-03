import json
import os
from pathlib import Path
import subprocess
import sys

import yaml

from repair_coordinator.workloads import ToolkitClient

SERVICE_ROOT = Path(__file__).parents[1]
REPOSITORY_ROOT = Path(__file__).parents[3]
RUN_ID = "00000000-0000-0000-0000-000000000123"


def test_toolkit_client_defaults_to_macos_device(monkeypatch) -> None:
    monkeypatch.delenv("FLUTTER_MCP_TOOLKIT_COMMAND", raising=False)

    client = ToolkitClient.from_environment()

    assert client._command == ["flutter-mcp-toolkit", "--flutter-device", "macos"]


def test_run_workload_maps_enter_text_to_unique_semantic_widget(tmp_path: Path) -> None:
    database_path = tmp_path / "repair-coordinator.db"
    toolkit_path = tmp_path / "fake-flutter-mcp-toolkit"
    capture_path = tmp_path / "toolkit-invocations.jsonl"
    workload_path = tmp_path / "enter_text.hs.yaml"
    write_fake_toolkit(toolkit_path)
    workload_path.write_text(
        """version: 1
name: enter_text_journey
variables:
  todo_title: normal-${run_id}
steps:
  - action: enter_text
    selector:
      type: textField
      label: New Todo
    text: ${todo_title}
"""
    )

    result = run_coordinator(
        "run-workload",
        str(workload_path),
        "--run-id",
        RUN_ID,
        database_path=database_path,
        extra_environment={
            "FLUTTER_MCP_TOOLKIT_COMMAND": str(toolkit_path),
            "FLUTTER_MCP_TOOLKIT_CAPTURE_PATH": str(capture_path),
        },
    )
    invocations = [
        json.loads(line) for line in capture_path.read_text().splitlines()
    ]

    assert result == {
        "name": "enter_text_journey",
        "run_id": RUN_ID,
        "status": "passed",
        "completed_steps": 1,
    }
    assert invocations == [
        {
            "name": "fmt_client_tool",
            "arguments": {
                "toolName": "todo_set_workload_run_id",
                "arguments": {"run_id": RUN_ID},
            },
        },
        {
            "name": "focus_window",
            "arguments": {},
        },
        {
            "name": "semantic_snapshot",
            "arguments": {},
        },
        {
            "name": "enter_text",
            "arguments": {
                "ref": "s_2",
                "snapshotId": 17,
                "text": f"normal-{RUN_ID}",
            },
        },
    ]


def test_run_workload_maps_tap_and_wait_for_steps(tmp_path: Path) -> None:
    database_path = tmp_path / "repair-coordinator.db"
    toolkit_path = tmp_path / "fake-flutter-mcp-toolkit"
    capture_path = tmp_path / "toolkit-invocations.jsonl"
    workload_path = tmp_path / "tap_and_wait.hs.yaml"
    write_fake_toolkit(toolkit_path)
    workload_path.write_text(
        """version: 1
name: tap_and_wait_journey
variables:
  todo_title: normal-${run_id}
steps:
  - action: tap
    selector:
      type: button
      label: Add
  - action: wait_for
    predicate:
      kind: text
      text: ${todo_title}
"""
    )

    result = run_coordinator(
        "run-workload",
        str(workload_path),
        "--run-id",
        RUN_ID,
        database_path=database_path,
        extra_environment={
            "FLUTTER_MCP_TOOLKIT_COMMAND": str(toolkit_path),
            "FLUTTER_MCP_TOOLKIT_CAPTURE_PATH": str(capture_path),
        },
    )
    invocations = [
        json.loads(line) for line in capture_path.read_text().splitlines()
    ]

    assert result == {
        "name": "tap_and_wait_journey",
        "run_id": RUN_ID,
        "status": "passed",
        "completed_steps": 2,
    }
    assert invocations == [
        {
            "name": "fmt_client_tool",
            "arguments": {
                "toolName": "todo_set_workload_run_id",
                "arguments": {"run_id": RUN_ID},
            },
        },
        {
            "name": "focus_window",
            "arguments": {},
        },
        {
            "name": "semantic_snapshot",
            "arguments": {},
        },
        {
            "name": "tap_widget",
            "arguments": {"ref": "s_3", "snapshotId": 17},
        },
        {
            "name": "wait_for",
            "arguments": {
                "predicate": {
                    "kind": "text",
                    "text": f"normal-{RUN_ID}",
                }
            },
        },
    ]


def test_run_workload_reports_ambiguous_selector_without_tapping(tmp_path: Path) -> None:
    database_path = tmp_path / "repair-coordinator.db"
    toolkit_path = tmp_path / "fake-flutter-mcp-toolkit"
    capture_path = tmp_path / "toolkit-invocations.jsonl"
    workload_path = tmp_path / "ambiguous_tap.hs.yaml"
    write_fake_toolkit(toolkit_path)
    workload_path.write_text(
        """version: 1
name: ambiguous_tap_journey
steps:
  - action: tap
    selector:
      type: button
      label: Add
"""
    )

    result = run_coordinator(
        "run-workload",
        str(workload_path),
        "--run-id",
        RUN_ID,
        database_path=database_path,
        extra_environment={
            "FLUTTER_MCP_TOOLKIT_COMMAND": str(toolkit_path),
            "FLUTTER_MCP_TOOLKIT_CAPTURE_PATH": str(capture_path),
            "FLUTTER_MCP_TOOLKIT_AMBIGUOUS_ADD": "true",
        },
    )
    invocations = [
        json.loads(line) for line in capture_path.read_text().splitlines()
    ]

    assert result["name"] == "ambiguous_tap_journey"
    assert result["run_id"] == RUN_ID
    assert result["status"] == "failed"
    assert result["completed_steps"] == 0
    assert result["failed_step"] == 0
    assert result["error"] == {
        "code": "selector_ambiguous",
        "selector": {"type": "button", "label": "Add"},
        "candidates": [
            {"ref": "s_3", "label": "Add", "type": "button"},
            {"ref": "s_4", "label": "Add", "type": "button"},
        ],
    }
    assert result["app_errors"] == {"errors": []}
    assert "failed_at" in result
    assert [invocation["name"] for invocation in invocations] == [
        "fmt_client_tool",
        "focus_window",
        "semantic_snapshot",
        "get_app_errors",
    ]


def test_run_workload_reports_toolkit_timeout_with_available_context(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "repair-coordinator.db"
    toolkit_path = tmp_path / "fake-flutter-mcp-toolkit"
    capture_path = tmp_path / "toolkit-invocations.jsonl"
    workload_path = tmp_path / "timeout.hs.yaml"
    write_fake_toolkit(toolkit_path)
    workload_path.write_text(
        """version: 1
name: timeout_journey
steps:
  - action: wait_for
    predicate:
      kind: text
      text: never-visible
"""
    )

    result = run_coordinator(
        "run-workload",
        str(workload_path),
        "--run-id",
        RUN_ID,
        database_path=database_path,
        extra_environment={
            "FLUTTER_MCP_TOOLKIT_COMMAND": str(toolkit_path),
            "FLUTTER_MCP_TOOLKIT_CAPTURE_PATH": str(capture_path),
            "FLUTTER_MCP_TOOLKIT_TIMEOUT_WAIT": "true",
        },
    )
    invocations = [
        json.loads(line) for line in capture_path.read_text().splitlines()
    ]

    assert result["status"] == "failed"
    assert result["completed_steps"] == 0
    assert result["failed_step"] == 0
    assert result["error"] == {
        "code": "timeout",
        "message": "wait predicate did not match",
    }
    assert result["last_snapshot"]["snapshot_id"] == 17
    assert result["app_errors"] == {"errors": []}
    assert [invocation["name"] for invocation in invocations] == [
        "fmt_client_tool",
        "focus_window",
        "wait_for",
        "semantic_snapshot",
        "get_app_errors",
    ]


def test_run_workload_retries_one_transient_toolkit_process_failure(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "repair-coordinator.db"
    toolkit_path = tmp_path / "fake-flutter-mcp-toolkit"
    capture_path = tmp_path / "toolkit-invocations.jsonl"
    failure_marker_path = tmp_path / "transient-failure-marker"
    workload_path = tmp_path / "transient_failure.hs.yaml"
    write_fake_toolkit(toolkit_path)
    workload_path.write_text("version: 1\nname: transient_failure\nsteps: []\n")

    result = run_coordinator(
        "run-workload",
        str(workload_path),
        "--run-id",
        RUN_ID,
        database_path=database_path,
        extra_environment={
            "FLUTTER_MCP_TOOLKIT_COMMAND": str(toolkit_path),
            "FLUTTER_MCP_TOOLKIT_CAPTURE_PATH": str(capture_path),
            "FLUTTER_MCP_TOOLKIT_TRANSIENT_FAILURE": "true",
            "FLUTTER_MCP_TOOLKIT_FAILURE_MARKER_PATH": str(failure_marker_path),
        },
    )

    assert result["status"] == "passed"
    assert [
        json.loads(line)["name"] for line in capture_path.read_text().splitlines()
    ] == ["fmt_client_tool", "focus_window"]


def test_run_workload_retries_transient_vm_service_disconnect(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "repair-coordinator.db"
    toolkit_path = tmp_path / "fake-flutter-mcp-toolkit"
    capture_path = tmp_path / "toolkit-invocations.jsonl"
    failure_marker_path = tmp_path / "vm-disconnect-marker"
    workload_path = tmp_path / "transient_vm_disconnect.hs.yaml"
    write_fake_toolkit(toolkit_path)
    workload_path.write_text("version: 1\nname: transient_vm_disconnect\nsteps: []\n")

    result = run_coordinator(
        "run-workload",
        str(workload_path),
        "--run-id",
        RUN_ID,
        database_path=database_path,
        extra_environment={
            "FLUTTER_MCP_TOOLKIT_COMMAND": str(toolkit_path),
            "FLUTTER_MCP_TOOLKIT_CAPTURE_PATH": str(capture_path),
            "FLUTTER_MCP_TOOLKIT_TRANSIENT_VM_DISCONNECT": "true",
            "FLUTTER_MCP_TOOLKIT_FAILURE_MARKER_PATH": str(failure_marker_path),
            "FLUTTER_MCP_TOOLKIT_RETRY_DELAY_SECONDS": "0",
        },
    )
    invocations = [
        json.loads(line) for line in capture_path.read_text().splitlines()
    ]

    assert result["status"] == "passed"
    assert [invocation["name"] for invocation in invocations] == [
        "fmt_client_tool",
        "fmt_client_tool",
        "focus_window",
    ]


def test_run_workload_reports_initial_toolkit_failure_without_traceback(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "repair-coordinator.db"
    toolkit_path = tmp_path / "fake-flutter-mcp-toolkit"
    capture_path = tmp_path / "toolkit-invocations.jsonl"
    workload_path = tmp_path / "initial_failure.hs.yaml"
    write_fake_toolkit(toolkit_path)
    workload_path.write_text("version: 1\nname: initial_failure\nsteps: []\n")

    result = run_coordinator(
        "run-workload",
        str(workload_path),
        "--run-id",
        RUN_ID,
        database_path=database_path,
        extra_environment={
            "FLUTTER_MCP_TOOLKIT_COMMAND": str(toolkit_path),
            "FLUTTER_MCP_TOOLKIT_CAPTURE_PATH": str(capture_path),
            "FLUTTER_MCP_TOOLKIT_PERMANENT_VM_DISCONNECT": "true",
            "FLUTTER_MCP_TOOLKIT_RETRY_DELAY_SECONDS": "0",
        },
    )

    assert result["status"] == "failed"
    assert result["completed_steps"] == 0
    assert result["failed_step"] is None
    assert result["error"] == {
        "code": -32000,
        "message": "VM service not connected",
    }
    assert result["last_snapshot"] is None
    assert result["app_errors"] is None


def test_run_workload_reports_focus_failure_before_running_steps(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "repair-coordinator.db"
    toolkit_path = tmp_path / "fake-flutter-mcp-toolkit"
    capture_path = tmp_path / "toolkit-invocations.jsonl"
    workload_path = tmp_path / "focus_failure.hs.yaml"
    write_fake_toolkit(toolkit_path)
    workload_path.write_text(
        """version: 1
name: focus_failure
steps:
  - action: wait_for
    predicate:
      kind: stable
      stableWindowMs: 300
"""
    )

    result = run_coordinator(
        "run-workload",
        str(workload_path),
        "--run-id",
        RUN_ID,
        database_path=database_path,
        extra_environment={
            "FLUTTER_MCP_TOOLKIT_COMMAND": str(toolkit_path),
            "FLUTTER_MCP_TOOLKIT_CAPTURE_PATH": str(capture_path),
            "FLUTTER_MCP_TOOLKIT_FAIL_FOCUS_WINDOW": "true",
        },
    )
    invocations = [
        json.loads(line) for line in capture_path.read_text().splitlines()
    ]

    assert result["status"] == "failed"
    assert result["completed_steps"] == 0
    assert result["failed_step"] is None
    assert result["error"] == {
        "code": "focus_window_failed",
        "message": "could not focus Flutter app window",
    }
    assert [invocation["name"] for invocation in invocations] == [
        "fmt_client_tool",
        "focus_window",
        "semantic_snapshot",
        "get_app_errors",
    ]


def test_reviewed_workloads_wait_for_todo_action_after_add() -> None:
    expected_wait_labels = {
        "normal_todo_journey.hs.yaml": ["Complete ${todo_title}"],
        "mixed_user_workload.hs.yaml": [
            "Complete ${first_todo_title}",
            "Delete ${second_todo_title}",
            "Delete ${backend_crash_todo_title}",
            "Complete ${client_crash_todo_title}",
        ],
    }

    for filename, expected_labels in expected_wait_labels.items():
        workload = yaml.safe_load((REPOSITORY_ROOT / "harness" / filename).read_text())
        steps = workload["steps"]
        add_indexes = [
            index
            for index, step in enumerate(steps)
            if step.get("action") == "tap"
            and step.get("selector", {}).get("label") == "Add"
        ]

        assert [
            steps[index + 1]["predicate"]["text"] for index in add_indexes
        ] == expected_labels


def run_coordinator(
    *arguments: str,
    database_path: Path,
    extra_environment: dict[str, str],
) -> object:
    """Run one workload CLI command and return its JSON response.

    `run-workload` does not use Coordinator task state, so this helper
    deliberately omits `REPAIR_COORDINATOR_DB_PATH`.
    """

    result = subprocess.run(
        [sys.executable, "-m", "repair_coordinator", *arguments],
        check=False,
        capture_output=True,
        cwd=SERVICE_ROOT,
        env={
            **os.environ,
            **extra_environment,
        },
        text=True,
    )

    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def write_fake_toolkit(toolkit_path: Path) -> None:
    """Write a deterministic Flutter MCP CLI replacement."""

    toolkit_path.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

capture_path = Path(os.environ["FLUTTER_MCP_TOOLKIT_CAPTURE_PATH"])
if sys.argv[1:] != ["serve"]:
    raise SystemExit("expected serve mode")

def print_vm_disconnect_response(request_id):
    print(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "ok": False,
                    "data": None,
                    "error": {
                        "code": -32000,
                        "message": "VM service not connected",
                    },
                },
            }
        ),
        flush=True,
    )

for line in sys.stdin:
    request = json.loads(line)
    if request["method"] == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": {}}), flush=True)
        continue
    if request["method"] != "command/execute":
        raise SystemExit(f"unsupported method: {request['method']}")

    name = request["params"]["name"]
    arguments = request["params"]["args"]
    if os.environ.get("FLUTTER_MCP_TOOLKIT_TRANSIENT_FAILURE") == "true":
        failure_marker = Path(os.environ["FLUTTER_MCP_TOOLKIT_FAILURE_MARKER_PATH"])
        if not failure_marker.exists():
            failure_marker.write_text("failed once")
            raise SystemExit(1)
    with capture_path.open("a") as capture:
        capture.write(json.dumps({"name": name, "arguments": arguments}) + "\\n")

    if os.environ.get("FLUTTER_MCP_TOOLKIT_TRANSIENT_VM_DISCONNECT") == "true":
        failure_marker = Path(os.environ["FLUTTER_MCP_TOOLKIT_FAILURE_MARKER_PATH"])
        if not failure_marker.exists():
            failure_marker.write_text("failed once")
            print_vm_disconnect_response(request["id"])
            continue
    if os.environ.get("FLUTTER_MCP_TOOLKIT_PERMANENT_VM_DISCONNECT") == "true":
        print_vm_disconnect_response(request["id"])
        continue
    if (
        name == "focus_window"
        and os.environ.get("FLUTTER_MCP_TOOLKIT_FAIL_FOCUS_WINDOW") == "true"
    ):
        print(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "result": {
                        "ok": False,
                        "data": None,
                        "error": {
                            "code": "focus_window_failed",
                            "message": "could not focus Flutter app window",
                        },
                    },
                }
            ),
            flush=True,
        )
        continue

    data = {}
    if name == "semantic_snapshot":
        nodes = [
            {
                "ref": "s_2",
                "label": "New Todo",
                "type": "textField",
                "actions": ["setText"],
            },
            {
                "ref": "s_3",
                "label": "Add",
                "type": "button",
                "actions": ["tap"],
            },
        ]
        if os.environ.get("FLUTTER_MCP_TOOLKIT_AMBIGUOUS_ADD") == "true":
            nodes.append(
                {
                    "ref": "s_4",
                    "label": "Add",
                    "type": "button",
                    "actions": ["tap"],
                }
            )
        data = {
            "snapshot_id": 17,
            "nodes": nodes,
        }
    if name == "get_app_errors":
        data = {"errors": []}
    if name == "wait_for" and os.environ.get("FLUTTER_MCP_TOOLKIT_TIMEOUT_WAIT") == "true":
        print(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "result": {
                        "ok": False,
                        "data": None,
                        "error": {
                            "code": "timeout",
                            "message": "wait predicate did not match",
                        },
                    },
                },
            ),
            flush=True,
        )
        continue
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
