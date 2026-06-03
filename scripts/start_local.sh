#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

if [[ ! -f .env ]]; then
  echo "Missing .env. Copy .env.example and fill in the Sentry values." >&2
  exit 1
fi

docker compose --env-file "$repository_root/.env" up -d --build

wait_for_service() {
  local name="$1"
  local url="$2"

  echo "Waiting for ${name}..."
  for _ in {1..60}; do
    if curl --fail --silent "$url" >/dev/null; then
      echo "${name} is ready at ${url}"
      return 0
    fi
    sleep 1
  done

  echo "${name} did not become ready within 60 seconds" >&2
  docker compose --env-file "$repository_root/.env" logs "$name" >&2
  return 1
}

wait_for_service victoria-logs http://localhost:9428/-/healthy
wait_for_service victoria-metrics http://localhost:8428/-/healthy
wait_for_service victoria-traces http://localhost:10428/-/healthy
wait_for_service todo-api http://localhost:8000/health
wait_for_service observability-gateway http://localhost:8001/health

echo "Start the Flutter app with: ./scripts/run_flutter.sh"
