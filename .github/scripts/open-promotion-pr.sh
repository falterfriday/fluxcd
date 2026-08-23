#!/usr/bin/env bash
# Commit the promotion edits to a branch and open a pull request.
#
# The PR is deliberately narrow: only chart version lines, one per release, so
# the diff is reviewable at a glance. Everything cluster-specific is untouched.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

if git diff --quiet; then
  echo "No changes to promote."
  exit 0
fi

branch="promotion/staging-to-production-$(date -u +%Y%m%d-%H%M%S)"
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git checkout -b "$branch"
git add -A
git commit -m "promote staging chart versions to production"
git push origin "$branch"

body="$(cat <<EOF
Promotes the chart versions staging has been running to production.

$(git diff main --stat)

Only exactly-pinned staging versions are promoted; releases on a range or with
no version are skipped, since promoting one would make production track a moving
target. Cluster-specific values — hostnames, storage sizes, replica counts — are
untouched.

Requested by @${ACTOR:-unknown} via the promotion workflow.
EOF
)"

gh pr create \
  --base main \
  --head "$branch" \
  --title "promote staging chart versions to production" \
  --body "$body" \
  --label "env:production"
