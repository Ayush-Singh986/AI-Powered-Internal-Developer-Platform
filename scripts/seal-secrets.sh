#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ( "$1" != "kind" && "$1" != "eks" ) ]]; then
  echo "Usage: scripts/seal-secrets.sh kind|eks" >&2
  exit 2
fi

: "${LLM_API_KEY:=}"
: "${RAG_SERVICE_TOKEN:?set RAG_SERVICE_TOKEN in the shell environment}"
: "${MODEL_SERVICE_API_KEY:?set MODEL_SERVICE_API_KEY in the shell environment}"
: "${LLM_GATEWAY_API_KEY:?set LLM_GATEWAY_API_KEY in the shell environment}"
: "${PORTAL_GATEWAY_API_KEY:?set PORTAL_GATEWAY_API_KEY in the shell environment}"
: "${LLM_GATEWAY_CLIENT_KEYS:?set LLM_GATEWAY_CLIENT_KEYS JSON in the shell environment}"
: "${AGENT_SERVICE_TOKEN:?set AGENT_SERVICE_TOKEN in the shell environment}"
: "${ALERTMANAGER_WEBHOOK_TOKEN:?set ALERTMANAGER_WEBHOOK_TOKEN in the shell environment}"
: "${AIOPS_ACTION_TOKEN:?set AIOPS_ACTION_TOKEN in the shell environment}"
: "${GRAFANA_ADMIN_PASSWORD:?set GRAFANA_ADMIN_PASSWORD in the shell environment}"
: "${GRAFANA_ADMIN_USER:=admin}"

service_tokens=(
  "$RAG_SERVICE_TOKEN"
  "$MODEL_SERVICE_API_KEY"
  "$LLM_GATEWAY_API_KEY"
  "$PORTAL_GATEWAY_API_KEY"
  "$AGENT_SERVICE_TOKEN"
  "$ALERTMANAGER_WEBHOOK_TOKEN"
  "$AIOPS_ACTION_TOKEN"
)
for ((index = 0; index < ${#service_tokens[@]}; index++)); do
  for ((other = index + 1; other < ${#service_tokens[@]}; other++)); do
    if [[ "${service_tokens[index]}" == "${service_tokens[other]}" ]]; then
      echo "Service, webhook, and action tokens must be distinct." >&2
      exit 2
    fi
  done
done

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output="$root/k8s/sealed-secrets/$1"
mkdir -p "$output"

seal() {
  local namespace="$1" secret_name="$2" key="$3" value="$4"
  local filename="${secret_name}-${namespace}.yaml"
  kubectl create secret generic "$secret_name" \
    --namespace "$namespace" \
    --from-literal="$key=$value" \
    --dry-run=client -o yaml |
    kubeseal --format yaml --scope namespace-wide \
      --controller-name sealed-secrets-controller \
      --controller-namespace kube-system \
      > "$output/$filename"
}

seal_grafana() {
  kubectl create secret generic grafana-admin \
    --namespace monitoring \
    --from-literal="admin-user=$GRAFANA_ADMIN_USER" \
    --from-literal="admin-password=$GRAFANA_ADMIN_PASSWORD" \
    --dry-run=client -o yaml |
    kubeseal --format yaml --scope namespace-wide \
      --controller-name sealed-secrets-controller \
      --controller-namespace kube-system \
      > "$output/grafana-admin-monitoring.yaml"
}

seal rag rag-auth RAG_SERVICE_TOKEN "$RAG_SERVICE_TOKEN"
seal model-serving model-serving-auth MODEL_SERVICE_API_KEY "$MODEL_SERVICE_API_KEY"
seal llm-gateway llm-gateway-auth LLM_GATEWAY_CLIENT_KEYS "$LLM_GATEWAY_CLIENT_KEYS"
seal llm-gateway model-serving-auth MODEL_SERVICE_API_KEY "$MODEL_SERVICE_API_KEY"
seal aiops-agent agent-service-auth AGENT_SERVICE_TOKEN "$AGENT_SERVICE_TOKEN"
seal aiops-agent llm-gateway-auth LLM_GATEWAY_API_KEY "$LLM_GATEWAY_API_KEY"
seal aiops-agent rag-auth RAG_SERVICE_TOKEN "$RAG_SERVICE_TOKEN"
seal aiops-agent alertmanager-webhook ALERTMANAGER_WEBHOOK_TOKEN "$ALERTMANAGER_WEBHOOK_TOKEN"
seal portal agent-service-auth AGENT_SERVICE_TOKEN "$AGENT_SERVICE_TOKEN"
seal portal llm-gateway-auth PORTAL_GATEWAY_API_KEY "$PORTAL_GATEWAY_API_KEY"
seal monitoring alertmanager-webhook ALERTMANAGER_WEBHOOK_TOKEN "$ALERTMANAGER_WEBHOOK_TOKEN"
seal model-serving llm-provider LLM_API_KEY "$LLM_API_KEY"
seal aiops-agent agent-auth AIOPS_ACTION_TOKEN "$AIOPS_ACTION_TOKEN"
seal_grafana

{
  printf 'resources:\n'
  while IFS= read -r filename; do
    printf '  - %s\n' "$filename"
  done < <(find "$output" -maxdepth 1 -type f -name '*.yaml' \
    ! -name kustomization.yaml -exec basename {} \; | sort)
} > "$output/kustomization.yaml"

echo "Created cluster-specific SealedSecret manifests in k8s/sealed-secrets/$1."
echo "Review that only SealedSecret resources are present, then commit and push those manifests."
