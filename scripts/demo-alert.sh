#!/usr/bin/env bash
set -euo pipefail

token="${SERVICE_AUTH_TOKEN:-demo-only-service-token}"
agent_url="${AIOPS_AGENT_URL:-http://127.0.0.1:8004}"
fingerprint="demo-quickstart-$(date +%s)"

payload="$(cat <<EOF
{"receiver":"aiops-agent","status":"firing","alerts":[{"status":"firing","fingerprint":"$fingerprint","labels":{"alertname":"DemoIncident","namespace":"rag","deployment":"rag","severity":"warning"},"annotations":{"summary":"Synthetic quick-start incident","description":"A sample service alert was sent to demonstrate incident diagnosis in the portal."}}]}
EOF
)"

curl --silent --show-error --fail-with-body \
  --connect-timeout 3 --max-time 15 \
  --request POST "$agent_url/alerts" \
  --header "Authorization: Bearer $token" \
  --header "Content-Type: application/json" \
  --data "$payload"
printf '\nSynthetic demo alert submitted. Refresh the portal incident feed.\n'
