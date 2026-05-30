#!/usr/bin/env bash
set -euo pipefail

api_url="${TODO_API_URL:-http://localhost:8000}"
logs_url="${VICTORIA_LOGS_URL:-http://localhost:9428}"
traces_url="${VICTORIA_TRACES_URL:-http://localhost:10428}"
metrics_url="${VICTORIA_METRICS_URL:-http://localhost:8428}"

uuid() {
  python3 -c 'from uuid import uuid4; print(uuid4())'
}

json_value() {
  local key="$1"
  python3 -c 'import json, sys; print(json.load(sys.stdin)[sys.argv[1]])' "$key"
}

wait_for_logs() {
  for _ in {1..60}; do
    logs="$(
      curl --fail --silent --show-error "$logs_url/select/logsql/query" \
        -d "query=_time:5m run_id:$run_id" \
        -d "limit=10"
    )"
    if printf '%s\n' "$logs" | python3 -c '
import json
import sys

rows = [json.loads(line) for line in sys.stdin if line.strip()]
methods = {row["method"] for row in rows}
assert {"POST", "PATCH", "DELETE"} <= methods
assert all(row["_msg"] == "http_request_completed" for row in rows)
' 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for VictoriaLogs entries" >&2
  return 1
}

wait_for_trace() {
  for _ in {1..60}; do
    if trace="$(
      curl --fail --silent --show-error \
        "$traces_url/select/jaeger/api/traces/$trace_id" 2>/dev/null
    )"; then
      printf '%s' "$trace" | python3 -c '
import json
import sys

spans = json.load(sys.stdin)["data"][0]["spans"]
operations = {span["operationName"] for span in spans}
assert {"POST /todos", "INSERT", "SELECT"} <= operations
'
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for VictoriaTraces entry" >&2
  return 1
}

assert_metric() {
  local query="$1"
  for _ in {1..60}; do
    if curl --fail --silent --show-error --get "$metrics_url/api/v1/query" \
      --data-urlencode "query=$query" \
      | python3 -c '
import json
import sys

assert json.load(sys.stdin)["data"]["result"]
' 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for VictoriaMetrics query: $query" >&2
  return 1
}

run_id="$(uuid)"
request_id="$(uuid)"
title="telemetry-smoke-$run_id"

create_response="$(
  curl --fail --silent --show-error -X POST "$api_url/todos" \
    -H "content-type: application/json" \
    -H "x-request-id: $request_id" \
    -H "x-workload-run-id: $run_id" \
    -H "authorization: Bearer should-not-leak" \
    -H "cookie: session=should-not-leak" \
    --data "{\"title\":\"$title\"}"
)"
todo_id="$(printf '%s' "$create_response" | json_value id)"

curl --fail --silent --show-error "$api_url/todos" >/dev/null
curl --fail --silent --show-error -X PATCH "$api_url/todos/$todo_id" \
  -H "content-type: application/json" \
  -H "x-workload-run-id: $run_id" \
  --data '{"completed":true}' >/dev/null
curl --fail --silent --show-error -X DELETE "$api_url/todos/$todo_id" \
  -H "x-workload-run-id: $run_id" >/dev/null

wait_for_logs
trace_id="$(
  printf '%s\n' "$logs" | python3 -c '
import json
import sys

rows = [json.loads(line) for line in sys.stdin if line.strip()]
print(next(row["trace_id"] for row in rows if row["method"] == "POST"))
'
)"
wait_for_trace

assert_metric 'todo_api_http_server_requests{method="POST",path_template="/todos",status_code="201"}'
assert_metric 'todo_api_http_server_duration_count{method="POST",path_template="/todos",status_code="201"}'

if printf '%s\n%s\n' "$logs" "$trace" | grep -F -e "$title" -e "should-not-leak"; then
  echo "Sensitive request data leaked into backend telemetry" >&2
  exit 1
fi

echo "Backend telemetry found in VictoriaLogs, VictoriaTraces, and VictoriaMetrics."
echo "run_id=$run_id"
echo "trace_id=$trace_id"
