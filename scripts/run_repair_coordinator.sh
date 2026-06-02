#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
state_root="${REPAIR_COORDINATOR_STATE_ROOT:-$repository_root/.repair_coordinator}"

mkdir -p "$state_root/worktrees"

export REPAIR_COORDINATOR_DB_PATH="${REPAIR_COORDINATOR_DB_PATH:-$state_root/tasks.db}"
export REPAIR_REPOSITORY_ROOT="${REPAIR_REPOSITORY_ROOT:-$repository_root}"
export REPAIR_WORKTREE_ROOT="${REPAIR_WORKTREE_ROOT:-$state_root/worktrees}"
export REPAIR_FLUTTER_LAUNCH_COMMAND="${REPAIR_FLUTTER_LAUNCH_COMMAND:-$repository_root/scripts/run_flutter_repair_worktree.sh}"
export REPAIR_CODEX_SANDBOX="${REPAIR_CODEX_SANDBOX:-danger-full-access}"

cd "$repository_root/services/repair_coordinator"
exec uv run python -m repair_coordinator run \
  --workload "$repository_root/harness/mixed_user_workload.hs.yaml" \
  "$@"
