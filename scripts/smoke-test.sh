#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
project="aiops-smoke-${$}"
compose=(docker compose -p "$project" -f docker-compose.yml -f docker-compose.demo.yml)

export AGENT_SERVICE_TOKEN="smoke-agent-token"
export RAG_SERVICE_TOKEN="smoke-rag-token"
export LLM_GATEWAY_API_KEY="smoke-gateway-token"
export PORTAL_GATEWAY_API_KEY="smoke-portal-token"
export LLM_GATEWAY_CLIENT_KEYS="{\"agent\":\"$LLM_GATEWAY_API_KEY\",\"portal\":\"$PORTAL_GATEWAY_API_KEY\"}"
export MODEL_SERVICE_API_KEY="smoke-model-token"
export ALERTMANAGER_WEBHOOK_TOKEN="smoke-webhook-token"
export AIOPS_ACTION_TOKEN="smoke-action-token"
export GRAFANA_ADMIN_PASSWORD="smoke-grafana-password"
export DAILY_TOKEN_LIMIT=100000

cleanup() {
  "${compose[@]}" down -v --remove-orphans
}
trap cleanup EXIT

"${compose[@]}" up --build -d
for endpoint in \
  http://localhost:8001/health \
  http://localhost:8002/health \
  http://localhost:8003/health \
  http://localhost:8004/health \
  http://localhost:8501/_stcore/health; do
  ready=false
  for _ in $(seq 1 60); do
    if curl --silent --fail "$endpoint" >/dev/null; then
      ready=true
      break
    fi
    sleep 2
  done
  if [[ "$ready" != true ]]; then
    echo "Service did not become healthy: $endpoint" >&2
    exit 1
  fi
done

unauthenticated_status="$(
  curl --silent --output /dev/null --write-out '%{http_code}' \
    --request POST http://localhost:8003/v1/chat/completions \
    --header 'Content-Type: application/json' \
    --data '{"messages":[{"role":"user","content":"unauthenticated check"}]}'
)"
[[ "$unauthenticated_status" == 401 ]] || {
  echo "Expected gateway 401, got $unauthenticated_status" >&2
  exit 1
}

alert='{"receiver":"aiops-agent","status":"firing","alerts":[{"status":"firing","fingerprint":"smoke-stable-alert","labels":{"alertname":"SmokeTest","namespace":"rag","deployment":"rag"},"annotations":{"summary":"Smoke test incident","description":"Runbook retrieval smoke test"}}]}'
for _ in $(seq 1 9); do
  curl --silent --show-error --fail --request POST http://localhost:8004/alerts \
    --header "Authorization: Bearer $ALERTMANAGER_WEBHOOK_TOKEN" \
    --header 'Content-Type: application/json' --data "$alert" >/dev/null
done
first_count=""
for _ in $(seq 1 60); do
  first_count="$(
    curl --silent --show-error --fail http://localhost:8003/metrics |
      awk '/^llm_gateway_requests_total\{outcome="success"\}/ {print $2}'
  )"
  if [[ "$first_count" == "1.0" || "$first_count" == "1" ]]; then
    break
  fi
  sleep 1
done
[[ "$first_count" == "1.0" || "$first_count" == "1" ]] || {
  echo "Expected exactly one successful LLM call after first alert, got ${first_count:-none}" >&2
  exit 1
}

curl --silent --show-error --fail --request POST http://localhost:8004/alerts \
  --header "Authorization: Bearer $ALERTMANAGER_WEBHOOK_TOKEN" \
  --header 'Content-Type: application/json' --data "$alert" >/dev/null
second_count="$(
  curl --silent --show-error --fail http://localhost:8003/metrics |
    awk '/^llm_gateway_requests_total\{outcome="success"\}/ {print $2}'
)"
[[ "$second_count" == "$first_count" ]] || {
  echo "Duplicate alert triggered an extra LLM call ($first_count -> $second_count)" >&2
  exit 1
}
incident_count="$(
  curl --silent --show-error --fail http://localhost:8004/incidents \
    --header "Authorization: Bearer $ALERTMANAGER_WEBHOOK_TOKEN" | jq 'length'
)"
[[ "$incident_count" == "1" ]] || {
  echo "Expected exactly one incident after duplicate alert, got $incident_count" >&2
  exit 1
}

echo "Smoke test passed: health checks, gateway 401, one incident, and one LLM call for duplicate alerts."
