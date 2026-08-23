#!/usr/bin/env bash
# Compare live cluster state against what this repository declares.
#
# Two questions, both invisible from the repo alone:
#   readiness  is every Flux Kustomization actually applied and Ready?
#   drift      does the live state still match the manifests?
#
# Drift matters more here than in most GitOps repos because almost every
# Kustomization runs with `prune: false`: a resource removed from git is left
# running in the cluster, and nothing reports it.
#
# Read-only. `flux diff` performs a server-side dry-run and mutates nothing.
# Requires cluster access, so this runs on a self-hosted runner.
#
# Usage: check-drift.sh <cluster-name>   (cluster-name is both the kube-context
#                                         and the clusters/<name> directory)
set -uo pipefail

cluster="${1:?usage: check-drift.sh <cluster-name>}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# No `set -e` here: every Kustomization must be checked even after one fails.
cd "$repo_root" || exit 1

summary="${GITHUB_STEP_SUMMARY:-/dev/null}"
problems=0

echo "== Kustomization readiness (${cluster}) =="
# Read status from the API rather than parsing `flux get` columns: a
# Kustomization that has never applied has no revision, which shifts the
# columns in exactly the case this check exists to catch.
if ! ready_json="$(kubectl get kustomizations.kustomize.toolkit.fluxcd.io -A \
    --context "$cluster" -o json 2>&1)"; then
  echo "::error title=Cluster unreachable::cannot reach context '${cluster}'"
  printf '%s\n' "$ready_json"
  exit 2
fi

not_ready="$(printf '%s\n' "$ready_json" | jq -r '
  .items[]
  | . as $k
  | ($k.status.conditions // [] | map(select(.type == "Ready")) | first) as $ready
  | select($ready == null or $ready.status != "True")
  | "\($k.metadata.name)\t\($ready.message // "no Ready condition")"
')"

printf '%s\n' "$ready_json" | jq -r '
  .items[]
  | ((.status.conditions // []) | map(select(.type == "Ready")) | first) as $r
  | "  \(.metadata.name | . + (" " * (18 - length)))ready=\($r.status // "unknown")"
'

if [ -n "$not_ready" ]; then
  while IFS=$'\t' read -r name message; do
    [ -n "$name" ] || continue
    echo "::error title=Kustomization not ready::${cluster}/${name}: ${message}"
    problems=$((problems + 1))
  done <<< "$not_ready"
fi

echo
echo "== Drift (${cluster}) =="
{
  echo "### Drift — \`${cluster}\`"
  echo
  echo "| kustomization | state |"
  echo "| --- | --- |"
} >> "$summary"

while IFS=$'\t' read -r name kpath file sops; do
  [ -n "$name" ] || continue
  case "$file" in "clusters/${cluster}/"*) ;; *) continue ;; esac

  # Encrypted Kustomizations cannot be diffed without the age key, which CI
  # deliberately does not hold. sops-guard.py covers their contents instead.
  if [ "$sops" = "yes" ]; then
    printf '  %-18s %s\n' "$name" "skipped (sops)"
    echo "| \`${name}\` | skipped (sops) |" >> "$summary"
    continue
  fi

  output="$(flux diff kustomization "$name" --path "$kpath" --context "$cluster" 2>&1)"
  case $? in
    0)
      printf '  %-18s %s\n' "$name" "in sync"
      echo "| \`${name}\` | in sync |" >> "$summary"
      ;;
    1)
      printf '  %-18s %s\n' "$name" "DRIFT"
      printf '%s\n' "$output" | sed 's/^/      /'
      echo "| \`${name}\` | **drift** |" >> "$summary"
      echo "::error title=Drift detected::${cluster}/${name} differs from the repository"
      problems=$((problems + 1))
      ;;
    *)
      printf '  %-18s %s\n' "$name" "DIFF FAILED"
      printf '%s\n' "$output" | sed 's/^/      /'
      echo "| \`${name}\` | diff failed |" >> "$summary"
      echo "::error title=Diff failed::${cluster}/${name} could not be diffed"
      problems=$((problems + 1))
      ;;
  esac
done <<< "$(python3 .github/scripts/list-kustomizations.py)"

echo >> "$summary"
echo
if [ "$problems" -gt 0 ]; then
  echo "check-drift: ${problems} problem(s) in ${cluster}"
  exit 1
fi
echo "check-drift: ${cluster} matches the repository"
