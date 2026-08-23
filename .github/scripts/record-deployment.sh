#!/usr/bin/env bash
# Reconcile a cluster and record the outcome as a GitHub Deployment.
#
# The Deployment object is what makes "what was running when" answerable later:
# during an incident, the question is which commit the cluster converged on and
# at what time, and that is not derivable from git history alone.
#
# Usage: record-deployment.sh <cluster> <git-sha>
set -uo pipefail

cluster="${1:?usage: record-deployment.sh <cluster> <git-sha>}"
git_sha="${2:?usage: record-deployment.sh <cluster> <git-sha>}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root" || exit 1

repository="${REPOSITORY:?REPOSITORY must be set}"

# Deployments are bookkeeping: if creating one fails, the reconcile result still
# matters more than the record of it, so this never aborts the run.
deployment_id="$(gh api "repos/${repository}/deployments" \
  -f ref="$git_sha" \
  -f environment="$cluster" \
  -f description="Flux reconcile of ${cluster}" \
  -F auto_merge=false \
  -F required_contexts='[]' \
  --jq '.id' 2>/dev/null || true)"

set_status() {
  [ -n "$deployment_id" ] || return 0
  gh api "repos/${repository}/deployments/${deployment_id}/statuses" \
    -f state="$1" -f description="$2" >/dev/null 2>&1 || true
}

set_status in_progress "Waiting for ${cluster} to converge"

if .github/scripts/reconcile.sh "$cluster" "${git_sha:0:8}"; then
  set_status success "${cluster} converged at ${git_sha:0:8}"
  echo "record-deployment: ${cluster} converged"
  exit 0
fi

set_status failure "${cluster} did not converge at ${git_sha:0:8}"
echo "::error title=Deployment failed::${cluster} did not converge at ${git_sha:0:8}"
exit 1
