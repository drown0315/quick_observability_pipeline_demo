#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repair_worktree="${1:?Pass the repair worktree path}"

set -a
source "$repository_root/.env"
set +a

for name in SENTRY_DSN APP_RELEASE APP_ENVIRONMENT; do
  if [[ -z "${!name:-}" ]]; then
    echo "Missing ${name} in .env" >&2
    exit 1
  fi
done

pkill -x todo_app >/dev/null 2>&1 || true

cd "$repair_worktree/app"
exec flutter run -d macos \
  --dart-define="SENTRY_DSN=${SENTRY_DSN}" \
  --dart-define="APP_RELEASE=${APP_RELEASE}" \
  --dart-define="APP_ENVIRONMENT=${APP_ENVIRONMENT}"
