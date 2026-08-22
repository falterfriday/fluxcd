#!/usr/bin/env python3

from __future__ import annotations

import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SETS = [
    ("enforce", "Enforced policies (blocking)", True),
    ("audit", "Audit policies (reporting only)", False),
]


def tidy(message: str) -> str:
    """Collapse a Kyverno message to its human-written part.

    Kyverno appends "rule <name> failed at path /spec/..." for every anyPattern
    branch it tried, which triples the length of an already-explicit message.
    """
    text = " ".join(str(message).split())
    text = text.removeprefix("validation error: ")
    marker = text.find(" rule ")
    return text[:marker] if marker != -1 else text


def run_set(policy_dir: Path, rendered: Path) -> tuple[Counter, list[tuple[str, str, str]]]:
    """Return (result counts, [(cluster, resource, message)]) for one policy set."""
    counts: Counter = Counter()
    findings: list[tuple[str, str, str]] = []

    for manifest in sorted(rendered.glob("*.yaml")):
        proc = subprocess.run(
            ["kyverno", "apply", str(policy_dir), "--resource", str(manifest), "--policy-report"],
            capture_output=True,
            text=True,
            cwd=REPO,
        )
        # Kyverno exits non-zero when a policy fails; that is expected here and
        # is read from the report rather than the exit status. Empty output with
        # a clean exit means no resource in this file matched any rule, which is
        # normal for e.g. a Kustomization holding only HelmRepositories.
        if not proc.stdout.strip():
            if proc.returncode == 0:
                continue
            print(f"ERROR: kyverno failed on {manifest.name}", file=sys.stderr)
            print(proc.stderr[-2000:], file=sys.stderr)
            raise SystemExit(2)

        report = None
        try:
            report = yaml.safe_load(proc.stdout)
        except yaml.YAMLError:
            pass
        if not isinstance(report, dict) or "results" not in report:
            print(f"ERROR: kyverno produced no usable report for {manifest.name}", file=sys.stderr)
            print(proc.stdout[-2000:] or proc.stderr[-2000:], file=sys.stderr)
            raise SystemExit(2)

        cluster = manifest.stem
        for result in report.get("results") or []:
            counts[result.get("result", "unknown")] += 1
            if result.get("result") != "fail":
                continue
            res = (result.get("resources") or [{}])[0]
            findings.append(
                (
                    cluster,
                    f"{res.get('kind', '?')}/{res.get('name', '?')}",
                    f"{result.get('rule', '?')}: {tidy(result.get('message', ''))}",
                )
            )

    return counts, findings


def emit(lines: list[str]) -> None:
    text = "\n".join(lines)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(text + "\n")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    rendered = Path(sys.argv[1])

    blocking_failures = 0
    for name, label, blocking in SETS:
        counts, findings = run_set(REPO / ".github" / "policies" / name, rendered)
        total_fail = counts.get("fail", 0)
        if blocking:
            blocking_failures = total_fail

        lines = [
            "",
            f"## {label}",
            "",
            f"pass: {counts.get('pass', 0)} | fail: {total_fail} | "
            f"skip: {counts.get('skip', 0)} | error: {counts.get('error', 0)}",
        ]
        if findings:
            lines += ["", "| cluster | resource | finding |", "| --- | --- | --- |"]
            lines += [f"| {c} | `{r}` | {m} |" for c, r, m in findings]
        emit(lines)

        if blocking:
            for cluster, resource, message in findings:
                print(f"::error title=Policy violation::{cluster} {resource} — {message}")

    if blocking_failures:
        emit(["", f"**{blocking_failures} enforced policy check(s) failed.**"])
        return 1

    emit(["", "Enforced policies clean."])
    return 0


if __name__ == "__main__":
    sys.exit(main())
