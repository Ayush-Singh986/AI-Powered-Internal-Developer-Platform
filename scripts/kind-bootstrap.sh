#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

if grep -R -q 'https://github.com/OWNER/REPO.git' argocd; then
  echo "Set your GitHub repository first: scripts/set-repo.sh OWNER/REPO" >&2
  exit 2
fi

if ! kind get clusters | grep -Fxq aiops-local; then
  kind create cluster --config k8s/kind-config.yaml
fi
kubectl apply -f https://raw.githubusercontent.com/argoproj/argo-cd/v3.5.6/manifests/install.yaml
kubectl -n argocd rollout status deployment/argocd-server --timeout=5m
kubectl apply -f argocd/root-application-kind.yaml
echo "Argo CD root app submitted. Wait for infra wave 0, seal secrets for this kind cluster, then push them for service wave 1."
