#!/usr/bin/env bash

set -uo pipefail

repository="${1:?usage: audit-branch-protection.sh <owner/repo>}"
summary="${GITHUB_STEP_SUMMARY:-/dev/null}"
problems=0

# The checks that should be required before a merge into main.
REQUIRED_CHECKS=(
  "sops guard"
  "lint"
  "build and schema-validate"
  "secret scan"
  "manifest policy and misconfiguration"
)

if ! protection="$(gh api "repos/${repository}/branches/main/protection" 2>&1)"; then
  echo "main is not protected, or the token cannot read protection settings:"
  printf '%s\n' "$protection" | sed 's/^/  /'
  {
    echo "### Branch protection — \`main\`"
    echo
    echo "**Not protected**, or protection is unreadable with this token."
    echo "Every check in this repository is advisory until protection requires it."
    echo
  } >> "$summary"
  echo "::warning title=main is unprotected::branch protection is not configured on main"
  exit 0
fi

echo "Branch protection on main:"

check() {
  local label="$1" actual="$2" want="$3"
  if [ "$actual" = "$want" ]; then
    printf '  %-42s %s\n' "$label" "ok (${actual})"
    echo "| ${label} | \`${actual}\` | ok |" >> "$summary"
  else
    printf '  %-42s %s\n' "$label" "EXPECTED ${want}, got ${actual}"
    echo "| ${label} | \`${actual}\` | expected \`${want}\` |" >> "$summary"
    echo "::warning title=Branch protection::${label} is '${actual}', expected '${want}'"
    problems=$((problems + 1))
  fi
}

{
  echo "### Branch protection — \`main\`"
  echo
  echo "| setting | value | state |"
  echo "| --- | --- | --- |"
} >> "$summary"

check "required pull request reviews" \
  "$(printf '%s' "$protection" | jq -r 'if .required_pull_request_reviews then "enabled" else "disabled" end')" \
  "enabled"
check "dismiss stale reviews" \
  "$(printf '%s' "$protection" | jq -r '.required_pull_request_reviews.dismiss_stale_reviews // false')" \
  "true"
check "require code owner reviews" \
  "$(printf '%s' "$protection" | jq -r '.required_pull_request_reviews.require_code_owner_reviews // false')" \
  "true"
check "require branches up to date" \
  "$(printf '%s' "$protection" | jq -r '.required_status_checks.strict // false')" \
  "true"
check "force pushes blocked" \
  "$(printf '%s' "$protection" | jq -r 'if .allow_force_pushes.enabled then "false" else "true" end')" \
  "true"
check "deletions blocked" \
  "$(printf '%s' "$protection" | jq -r 'if .allow_deletions.enabled then "false" else "true" end')" \
  "true"

configured_checks="$(printf '%s' "$protection" | jq -r '.required_status_checks.contexts // [] | .[]')"
echo
echo "Required status checks:"
for wanted in "${REQUIRED_CHECKS[@]}"; do
  if printf '%s\n' "$configured_checks" | grep -qxF "$wanted"; then
    printf '  %-42s %s\n' "$wanted" "required"
  else
    printf '  %-42s %s\n' "$wanted" "NOT REQUIRED"
    echo "| required check: ${wanted} | missing | expected required |" >> "$summary"
    echo "::warning title=Check not required::'${wanted}' is not a required status check on main"
    problems=$((problems + 1))
  fi
done

echo >> "$summary"
echo
if [ "$problems" -gt 0 ]; then
  # Reported, not enforced: protection settings are the repository owner's call,
  # and failing the job every month would not change them.
  echo "audit-branch-protection: ${problems} setting(s) differ from the intended configuration"
  exit 0
fi
echo "audit-branch-protection: main is protected as intended"
