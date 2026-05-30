#!/usr/bin/env bash
set -euo pipefail

docker compose up -d --build todo-api

echo "Waiting for todo-api health check..."
for _ in {1..30}; do
  if curl --fail --silent http://localhost:8000/health >/dev/null; then
    echo "todo-api is ready at http://localhost:8000"
    echo "Start the Flutter app with: (cd app && flutter run -d macos)"
    exit 0
  fi
  sleep 1
done

echo "todo-api did not become healthy within 30 seconds" >&2
docker compose logs todo-api >&2
exit 1
