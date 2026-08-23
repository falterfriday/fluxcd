#!/usr/bin/env python3
"""Compare staging against production and prepare a promotion.

The two clusters are deliberately different — hostnames, storage sizes, replica
counts — so a blanket copy would be wrong. The one thing that *should* travel
from staging to production is the chart version that staging has been running,
which is what "promotion" means in this repository's branch history.

Safety rule: only an exactly-pinned staging version is promotable. If staging
is on a range or has no version at all, promoting it would make production
track a moving target, so it is reported and skipped.

  promotion.py <rendered-dir>           report what could be promoted
  promotion.py <rendered-dir> --apply   edit the production manifests
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
EXACT = re.compile(r"^v?\d+\.\d+\.\d+$")
# Per-cluster overlays; the shared bases under infrastructure/ and apps/ are
# common to both clusters and so are never a promotion target.
OVERLAY_DIRS = ("apps-overlay", "sso")


def effective_versions(rendered: Path, cluster: str) -> dict[str, str]:
    versions: dict[str, str] = {}
    for manifest in sorted(rendered.glob(f"{cluster}--*.yaml")):
        for doc in yaml.safe_load_all(manifest.read_text()):
            if not isinstance(doc, dict) or doc.get("kind") != "HelmRelease":
                continue
            chart = ((doc.get("spec") or {}).get("chart") or {}).get("spec") or {}
            versions[doc["metadata"]["name"]] = str(chart.get("version") or "")
    return versions


def find_overlay_file(cluster: str, release: str) -> Path | None:
    """Locate the per-cluster overlay declaring this HelmRelease."""
    for subdir in OVERLAY_DIRS:
        directory = REPO / "clusters" / cluster / subdir
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            for doc in yaml.safe_load_all(path.read_text()):
                if isinstance(doc, dict) and doc.get("kind") == "HelmRelease" \
                        and doc["metadata"]["name"] == release:
                    return path
    return None


def set_version(path: Path, release: str, version: str) -> bool:
    """Rewrite the chart version in place, preserving comments and layout.

    A targeted line edit rather than a YAML round-trip: dumping the document
    back out would strip the comments and reflow the values blocks.
    """
    lines = path.read_text().splitlines(keepends=True)
    in_release = False
    in_chart_spec = False
    for index, line in enumerate(lines):
        if re.match(r"^\s*name:\s*" + re.escape(release) + r"\s*$", line):
            in_release = True
        if in_release and re.match(r"^\s*chart:\s*$", line):
            in_chart_spec = True
        if in_chart_spec and re.match(r"^\s*version:\s*", line):
            indent = re.match(r"^(\s*)", line).group(1)
            lines[index] = f'{indent}version: "{version}"\n'
            path.write_text("".join(lines))
            return True
    return False


def emit(text: str) -> None:
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(text + "\n")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply_changes = "--apply" in sys.argv
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2

    rendered = Path(args[0])
    staging = effective_versions(rendered, "staging")
    production = effective_versions(rendered, "production")

    promotable: list[tuple[str, str, str, Path]] = []
    blocked: list[tuple[str, str]] = []
    aligned: list[str] = []

    for release in sorted(set(staging) & set(production)):
        stage_version, prod_version = staging[release], production[release]
        if stage_version == prod_version:
            aligned.append(release)
            continue
        if not EXACT.match(stage_version):
            blocked.append(
                (release, f"staging is on `{stage_version or 'no version'}`, not an exact pin")
            )
            continue
        overlay = find_overlay_file("production", release)
        if overlay is None:
            blocked.append((release, "no production overlay declares this HelmRelease"))
            continue
        promotable.append((release, prod_version, stage_version, overlay))

    lines = ["", "## Promotion: staging → production", ""]
    if promotable:
        lines += ["| release | production | staging | file |", "| --- | --- | --- | --- |"]
        lines += [
            f"| `{r}` | `{p}` | `{s}` | `{f.relative_to(REPO)}` |"
            for r, p, s, f in promotable
        ]
    else:
        lines.append("Nothing to promote — every comparable release matches.")
    if blocked:
        lines += ["", "**Skipped:**", ""]
        lines += [f"- `{release}` — {why}" for release, why in blocked]
    if aligned:
        lines += ["", f"Already aligned: {', '.join(f'`{r}`' for r in aligned)}"]
    emit("\n".join(lines))

    if apply_changes:
        changed = 0
        for release, _, stage_version, overlay in promotable:
            if set_version(overlay, release, stage_version):
                print(f"  updated {overlay.relative_to(REPO)}: {release} -> {stage_version}")
                changed += 1
            else:
                print(f"  could not locate a version line for {release} in {overlay}")
        print(f"\npromotion: {changed} file(s) updated")

    # Signal to the workflow whether a PR is warranted.
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a") as fh:
            fh.write(f"promotable={len(promotable)}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
