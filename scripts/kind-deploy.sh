#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
tag="$(git rev-parse --short HEAD)"

for service in rag model-serving llm-gateway aiops-agent portal mock-llm; do
  case "$service" in
    rag) image="local/aiops-rag" ;;
    model-serving) image="local/aiops-model-serving" ;;
    llm-gateway) image="local/aiops-llm-gateway" ;;
    aiops-agent) image="local/aiops-agent" ;;
    portal) image="local/aiops-portal" ;;
    mock-llm) image="local/aiops-mock-llm" ;;
  esac
  docker build -t "$image:$tag" "./services/$service"
  kind load docker-image "$image:$tag" --name aiops-local
  (
    cd "k8s/overlays/kind/$service"
    kustomize edit set image "$image=$image:$tag"
  )
done

echo "Images loaded. Commit and push the updated k8s/overlays/kind/*/kustomization.yaml files for Argo CD to reconcile."
