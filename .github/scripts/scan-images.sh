#!/usr/bin/env bash

set -euo pipefail

rendered="${1:?usage: scan-images.sh <rendered-dir> <output-dir>}"
outdir="${2:?usage: scan-images.sh <rendered-dir> <output-dir>}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

mkdir -p "$outdir"
summary="${GITHUB_STEP_SUMMARY:-/dev/stdout}"

images="$(python3 .github/scripts/list-images.py "$rendered")"
echo "Scanning $(printf '%s\n' "$images" | wc -l) images"

{
  echo "## Image vulnerability scan"
  echo
  echo "| image | critical | high | status |"
  echo "| --- | ---: | ---: | --- |"
} >> "$summary"

index=0
while IFS= read -r image; do
  [ -n "$image" ] || continue
  index=$((index + 1))
  safe="$(printf '%s' "$image" | tr '/:@' '___')"

  if ! trivy image "$image" \
      --severity HIGH,CRITICAL --scanners vuln --quiet \
      --format json --output "${outdir}/${safe}.json" 2>"${outdir}/${safe}.err"; then
    echo "  ${image}: SCAN FAILED"
    echo "| \`${image}\` | – | – | scan failed |" >> "$summary"
    continue
  fi

  crit="$(jq '[.Results[]?.Vulnerabilities[]? | select(.Severity=="CRITICAL")] | length' "${outdir}/${safe}.json")"
  high="$(jq '[.Results[]?.Vulnerabilities[]? | select(.Severity=="HIGH")] | length' "${outdir}/${safe}.json")"
  echo "  ${image}: CRITICAL=${crit} HIGH=${high}"
  echo "| \`${image}\` | ${crit} | ${high} | scanned |" >> "$summary"

  trivy image "$image" \
    --severity HIGH,CRITICAL --scanners vuln --quiet \
    --format sarif --output "${outdir}/${safe}.sarif" 2>/dev/null || true
done <<< "$images"

echo >> "$summary"
echo "scan-images: scanned ${index} images"
