#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

if [[ $# -ne 1 || ! "$1" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo "Usage: make kind-up REPO=OWNER/REPOSITORY" >&2
  exit 2
fi

: "${SERVICE_AUTH_TOKEN:?export SERVICE_AUTH_TOKEN before running make kind-up}"
: "${AIOPS_ACTION_TOKEN:?export AIOPS_ACTION_TOKEN before running make kind-up}"
: "${GRAFANA_ADMIN_PASSWORD:?export GRAFANA_ADMIN_PASSWORD before running make kind-up}"

scripts/set-repo.sh "$1"
if ! git diff --quiet -- argocd || ! git diff --cached --quiet -- argocd; then
  echo "Argo CD repository URLs changed. Commit and push them, then rerun make kind-up:" >&2
  echo "  git add argocd" >&2
  echo "  git commit -m 'chore: configure Argo CD repository'" >&2
  echo "  git push" >&2
  exit 3
fi

make kind
kubectl -n kube-system rollout status deployment/sealed-secrets-controller --timeout=5m
scripts/seal-secrets.sh kind
make kind-deploy

cat <<'EOF'
Local cluster is bootstrapped and images/secrets are prepared.
Commit and push these generated desired-state changes for Argo CD to deploy:
  k8s/sealed-secrets/kind/
  k8s/overlays/kind/

Then wait for all Argo CD Applications to become Healthy and Synced.
EOF
