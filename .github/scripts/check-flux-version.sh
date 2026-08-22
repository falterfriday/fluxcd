#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

dry_run=false
[ "${1:-}" = "--dry-run" ] && dry_run=true

pinned="$(grep -E '^\s+FLUX_VERSION:' .github/workflows/validate.yaml \
  | head -n 1 | sed -E 's/.*FLUX_VERSION:\s*"?([^"]+)"?.*/\1/')"
if [ -z "$pinned" ]; then
  echo "::error::could not read FLUX_VERSION from .github/workflows/validate.yaml"
  exit 1
fi

latest="$(curl -sSL https://api.github.com/repos/fluxcd/flux2/releases/latest \
  | jq -r '.tag_name')"
if [ -z "$latest" ] || [ "$latest" = "null" ]; then
  echo "::error::could not determine the latest flux2 release"
  exit 1
fi

pinned_tag="v${pinned#v}"
echo "pinned:  ${pinned_tag}"
echo "latest:  ${latest}"

if [ "$pinned_tag" = "$latest" ]; then
  echo "Flux is up to date."
  exit 0
fi

title="Flux ${latest} is available (repo pins ${pinned_tag})"
echo "::notice title=Flux update available::${title}"

if [ "$dry_run" = true ]; then
  echo "(dry run — no issue created)"
  exit 0
fi

# One open issue at a time: re-running monthly should not accumulate duplicates.
existing="$(gh issue list --state open --label flux-upgrade --json number,title \
  --jq '.[0].number' 2>/dev/null || true)"

body="$(cat <<EOF
Upstream Flux release **${latest}** is newer than the version this repository
pins (\`${pinned_tag}\`).

\`FLUX_VERSION\` in \`.github/workflows/validate.yaml\` sets the CLI used to
render manifests in CI. It should track the version the clusters actually run:
a CI CLI newer than the cluster can accept manifests the cluster then rejects.

Upgrade checklist:

- [ ] Read the [release notes](https://github.com/fluxcd/flux2/releases/tag/${latest})
- [ ] Upgrade the Flux Operator on staging, confirm all Kustomizations reconcile
- [ ] Upgrade production
- [ ] Bump \`FLUX_VERSION\` in \`.github/workflows/validate.yaml\`

_Opened automatically by the flux-version-check workflow._
EOF
)"

if [ -n "$existing" ]; then
  echo "Updating existing issue #${existing}"
  gh issue edit "$existing" --title "$title" --body "$body"
else
  echo "Opening a new tracking issue"
  gh issue create --title "$title" --body "$body" --label flux-upgrade
fi
