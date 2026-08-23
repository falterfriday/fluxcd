#!/usr/bin/env bash
# Report branches already merged into main, and optionally delete them.
#
# This repository accumulates them: each change ships on its own branch and
# nothing cleans up afterwards. Merged branches are noise, and noise makes the
# genuinely unmerged branch — the one holding work someone forgot — invisible.
#
# Deletion is opt-in via DELETE_MERGED=true, because deleting a branch is not
# something a scheduled job should decide on its own.
set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root" || exit 1

delete_merged="${DELETE_MERGED:-false}"
summary="${GITHUB_STEP_SUMMARY:-/dev/null}"

git fetch --prune origin >/dev/null 2>&1 || true

merged=()
unmerged=()
# Iterate full refnames: `%(refname:short)` renders refs/remotes/origin/HEAD as
# the bare string "origin", which no amount of prefix-stripping turns into a
# branch name.
while IFS= read -r ref; do
  branch="${ref#refs/remotes/origin/}"
  case "$branch" in main | HEAD | "") continue ;; esac
  if git merge-base --is-ancestor "origin/${branch}" origin/main 2>/dev/null; then
    merged+=("$branch")
  else
    unmerged+=("$branch")
  fi
done < <(git for-each-ref --format='%(refname)' refs/remotes/origin/)

echo "Merged into main (${#merged[@]}):"
printf '  %s\n' "${merged[@]:-<none>}"
echo
echo "Not merged (${#unmerged[@]}):"
printf '  %s\n' "${unmerged[@]:-<none>}"

{
  echo "### Branch hygiene"
  echo
  echo "- merged into main: **${#merged[@]}**"
  echo "- not merged: **${#unmerged[@]}**"
  echo
  if [ "${#merged[@]}" -gt 0 ]; then
    echo "<details><summary>Merged branches</summary>"
    echo
    printf -- "- \`%s\`\n" "${merged[@]}"
    echo
    echo "</details>"
    echo
  fi
  if [ "${#unmerged[@]}" -gt 0 ]; then
    echo "**Unmerged — these hold work that never landed:**"
    echo
    printf -- "- \`%s\`\n" "${unmerged[@]}"
    echo
  fi
} >> "$summary"

if [ "$delete_merged" != "true" ]; then
  echo
  echo "Report only. Re-run with delete_merged_branches enabled to remove the merged branches."
  exit 0
fi

if [ "${#merged[@]}" -eq 0 ]; then
  echo
  echo "Nothing to delete."
  exit 0
fi

echo
for branch in "${merged[@]}"; do
  if git push origin --delete "$branch" >/dev/null 2>&1; then
    echo "  deleted ${branch}"
  else
    echo "  could not delete ${branch}"
  fi
done
