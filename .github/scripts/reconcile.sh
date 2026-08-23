#!/usr/bin/env bash
# Close the GitOps feedback loop after a merge.
#
# Without this, merging tells you nothing: Flux picks the commit up on its own
# schedule (every 1h here) and any failure surfaces only in the cluster. This
# pushes the source, waits for every Kustomization to report the merged commit,
# and fails the run if convergence does not happen.
#
# Run manually from a machine with cluster access — useful after merging to
# confirm the clusters actually converged on the new commit.
#
#   reconcile.sh <cluster> [<git-sha>]              trigger, then wait
#   reconcile.sh <cluster> [<git-sha>] --check-only wait only, trigger nothing
set -uo pipefail

cluster="${1:?usage: reconcile.sh <cluster> [<git-sha>] [--check-only]}"
expected_sha=""
check_only=false
for arg in "${@:2}"; do
  case "$arg" in
    --check-only) check_only=true ;;
    *) expected_sha="$arg" ;;
  esac
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root" || exit 1

timeout_seconds="${RECONCILE_TIMEOUT:-300}"
summary="${GITHUB_STEP_SUMMARY:-/dev/null}"

if [ "$check_only" = false ]; then
  echo "Triggering source reconciliation on ${cluster}"
  if ! flux reconcile source git flux-system --context "$cluster"; then
    echo "::error title=Reconcile failed::could not reconcile the git source on ${cluster}"
    exit 1
  fi
else
  echo "Check-only: not triggering reconciliation on ${cluster}"
fi

echo "Waiting up to ${timeout_seconds}s for ${cluster} to converge"
deadline=$(( $(date +%s) + timeout_seconds ))
last_report=""

while :; do
  if ! json="$(kubectl get kustomizations.kustomize.toolkit.fluxcd.io -A \
      --context "$cluster" -o json 2>&1)"; then
    echo "::error title=Cluster unreachable::cannot reach context '${cluster}'"
    exit 2
  fi

  # A Kustomization counts as converged when its Ready condition is True and,
  # when a SHA was supplied, its applied revision contains that SHA.
  pending="$(printf '%s\n' "$json" | jq -r --arg sha "$expected_sha" '
    .items[]
    | . as $k
    | ((.status.conditions // []) | map(select(.type == "Ready")) | first) as $r
    | select(
        ($r == null or $r.status != "True")
        or ($sha != "" and (($k.status.lastAppliedRevision // "") | contains($sha) | not))
      )
    | "\($k.metadata.name): ready=\($r.status // "unknown") revision=\($k.status.lastAppliedRevision // "none")"
  ')"

  if [ -z "$pending" ]; then
    echo "All Kustomizations on ${cluster} are Ready${expected_sha:+ at ${expected_sha}}"
    {
      echo "### Reconcile — \`${cluster}\`"
      echo
      echo "Converged${expected_sha:+ at \`${expected_sha}\`}."
      echo
    } >> "$summary"
    exit 0
  fi

  if [ "$pending" != "$last_report" ]; then
    echo "  waiting on:"
    printf '%s\n' "$pending" | sed 's/^/    /'
    last_report="$pending"
  fi

  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo
    echo "::error title=Reconcile timeout::${cluster} did not converge within ${timeout_seconds}s"
    printf '%s\n' "$pending" | sed 's/^/  /'
    {
      echo "### Reconcile — \`${cluster}\`"
      echo
      echo "**Did not converge within ${timeout_seconds}s.**"
      echo
      echo '```'
      printf '%s\n' "$pending"
      echo '```'
      echo
    } >> "$summary"
    exit 1
  fi

  sleep 10
done
