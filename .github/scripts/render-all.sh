#!/usr/bin/env bash

set -euo pipefail

outdir="${1:?usage: render-all.sh <output-directory>}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

mkdir -p "$outdir"
rm -f "$outdir"/*.yaml

count=0
while IFS=$'\t' read -r name kpath file sops; do
  [ -n "$name" ] || continue

  [ "$sops" = "yes" ] && continue
  cluster="$(printf '%s' "$file" | awk -F/ '{print $2}')"
  flux build kustomization "$name" \
    --path "$kpath" --kustomization-file "$file" --dry-run \
    > "${outdir}/${cluster}--${name}.yaml"
  count=$((count + 1))
done <<< "$(python3 .github/scripts/list-kustomizations.py)"

echo "render-all: wrote ${count} rendered Kustomizations to ${outdir}"
