#!/usr/bin/env bash
set -euo pipefail

docker compose up -d --build

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
  docker compose logs "$name" >&2
  return 1
}

wait_for_service victoria-logs http://localhost:9428/-/healthy
wait_for_service victoria-metrics http://localhost:8428/-/healthy
wait_for_service victoria-traces http://localhost:10428/-/healthy
wait_for_service todo-api http://localhost:8000/health

echo "Start the Flutter app with: (cd app && flutter run -d macos)"
