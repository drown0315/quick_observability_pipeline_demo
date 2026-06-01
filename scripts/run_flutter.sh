#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

if [[ ! -f .env ]]; then
  echo "Missing .env. Copy .env.example and fill in the Sentry values." >&2
  exit 1
fi

set -a
source .env
set +a

for name in SENTRY_DSN APP_RELEASE APP_ENVIRONMENT; do
  if [[ -z "${!name:-}" ]]; then
    echo "Missing ${name} in .env" >&2
    exit 1
  fi
done

cd app
exec flutter run -d macos \
  --dart-define="SENTRY_DSN=${SENTRY_DSN}" \
  --dart-define="APP_RELEASE=${APP_RELEASE}" \
  --dart-define="APP_ENVIRONMENT=${APP_ENVIRONMENT}"
