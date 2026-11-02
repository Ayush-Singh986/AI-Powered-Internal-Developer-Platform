#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

export SERVICE_AUTH_TOKEN="${SERVICE_AUTH_TOKEN:-demo-only-service-token}"
export LLM_GATEWAY_API_KEY="${LLM_GATEWAY_API_KEY:-$SERVICE_AUTH_TOKEN}"
export MODEL_SERVICE_API_KEY="${MODEL_SERVICE_API_KEY:-$SERVICE_AUTH_TOKEN}"
export AIOPS_ACTION_TOKEN="${AIOPS_ACTION_TOKEN:-demo-only-action-token}"
export GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-demo-only-password}"
export DAILY_TOKEN_LIMIT="${DAILY_TOKEN_LIMIT:-100000}"

docker compose -f docker-compose.yml -f docker-compose.demo.yml up --build -d
echo "Demo mode is running: http://localhost:8501 (canned LLM responses; no provider key)."
