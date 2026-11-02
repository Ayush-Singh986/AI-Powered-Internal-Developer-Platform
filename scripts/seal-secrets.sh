#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ( "$1" != "kind" && "$1" != "eks" ) ]]; then
  echo "Usage: scripts/seal-secrets.sh kind|eks" >&2
  exit 2
fi

: "${LLM_API_KEY:=}"
: "${SERVICE_AUTH_TOKEN:?set SERVICE_AUTH_TOKEN in the shell environment}"
: "${AIOPS_ACTION_TOKEN:?set AIOPS_ACTION_TOKEN in the shell environment}"
: "${GRAFANA_ADMIN_PASSWORD:?set GRAFANA_ADMIN_PASSWORD in the shell environment}"
: "${GRAFANA_ADMIN_USER:=admin}"

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

for namespace in rag model-serving llm-gateway aiops-agent portal monitoring; do
  seal "$namespace" service-auth SERVICE_AUTH_TOKEN "$SERVICE_AUTH_TOKEN"
done
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
