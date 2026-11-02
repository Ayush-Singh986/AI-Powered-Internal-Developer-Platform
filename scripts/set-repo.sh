#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: scripts/set-repo.sh OWNER/REPO" >&2
  exit 2
fi
case "$1" in
  */*) ;;
  *)
  echo "Repository must be written as OWNER/REPO." >&2
  exit 2
  ;;
esac

owner="${1%%/*}"
repo="${1#*/}"
case "$owner:$repo" in
  :*|*:)
    echo "Repository must be written as OWNER/REPO." >&2
    exit 2
    ;;
esac
case "$owner$repo" in
  *[!A-Za-z0-9_.-]*|*/*)
    echo "Repository must be written as OWNER/REPO." >&2
    exit 2
    ;;
esac

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
find "$root/argocd" -type f \( -name '*.yaml' -o -name '*.yml' \) \
  -exec sed -i "s|https://github.com/OWNER/REPO.git|https://github.com/$1.git|g" {} +
echo "Updated Argo CD repository URLs to https://github.com/$1.git"
