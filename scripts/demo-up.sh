#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

export AGENT_SERVICE_TOKEN="${AGENT_SERVICE_TOKEN:-demo-only-agent-token}"
export RAG_SERVICE_TOKEN="${RAG_SERVICE_TOKEN:-demo-only-rag-token}"
export LLM_GATEWAY_API_KEY="${LLM_GATEWAY_API_KEY:-demo-only-gateway-token}"
export PORTAL_GATEWAY_API_KEY="${PORTAL_GATEWAY_API_KEY:-demo-only-portal-token}"
if [[ -z "${LLM_GATEWAY_CLIENT_KEYS:-}" ]]; then
  export LLM_GATEWAY_CLIENT_KEYS="{\"agent\":\"$LLM_GATEWAY_API_KEY\",\"portal\":\"$PORTAL_GATEWAY_API_KEY\"}"
fi
export MODEL_SERVICE_API_KEY="${MODEL_SERVICE_API_KEY:-demo-only-model-token}"
export AIOPS_ACTION_TOKEN="${AIOPS_ACTION_TOKEN:-demo-only-action-token}"
export ALERTMANAGER_WEBHOOK_TOKEN="${ALERTMANAGER_WEBHOOK_TOKEN:-demo-only-webhook-token}"
export GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-demo-only-password}"
export DAILY_TOKEN_LIMIT="${DAILY_TOKEN_LIMIT:-100000}"

docker compose -f docker-compose.yml -f docker-compose.demo.yml up --build -d
echo "Demo mode is running: http://localhost:8501 (canned LLM responses; no provider key)."
