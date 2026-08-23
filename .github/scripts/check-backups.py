#!/usr/bin/env python3
"""Verify CloudNativePG backup coverage and freshness for one cluster.

Two failure modes matter and only one of them is visible in a dashboard:

  coverage   a CNPG Cluster with no ScheduledBackup at all. Nothing alerts on
             this, because nothing is failing — there is simply no backup.
  freshness  a ScheduledBackup that exists but whose most recent completed
             Backup has aged past its window, or whose latest attempt failed.

Read-only: issues `kubectl get`, never mutates.

Usage: check-backups.py <kube-context> [--max-age-hours N]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

CNPG = "postgresql.cnpg.io"
DEFAULT_MAX_AGE_HOURS = 36  # daily schedule plus a full missed run of headroom


def kget(context: str, resource: str) -> list[dict]:
    proc = subprocess.run(
        ["kubectl", "get", resource, "-A", "--context", context, "-o", "json"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        print(f"::error::kubectl get {resource} failed: {proc.stderr.strip()}")
        raise SystemExit(2)
    return json.loads(proc.stdout).get("items", [])


def age_hours(timestamp: str) -> float | None:
    try:
        when = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return (datetime.now(timezone.utc) - when).total_seconds() / 3600.0


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    context = args[0]

    max_age = DEFAULT_MAX_AGE_HOURS
    for arg in sys.argv[1:]:
        if arg.startswith("--max-age-hours="):
            max_age = float(arg.split("=", 1)[1])

    clusters = kget(context, f"clusters.{CNPG}")
    scheduled = kget(context, f"scheduledbackups.{CNPG}")
    backups = kget(context, f"backups.{CNPG}")

    # Group every attempt by cluster, newest first. Judging a cluster by whether
    # *any* backup ever failed would flag clusters that recovered weeks ago —
    # only the most recent attempt says whether backups work right now.
    attempts: dict[tuple[str, str], list[dict]] = {}
    for backup in backups:
        meta, spec = backup["metadata"], backup.get("spec", {})
        key = (meta["namespace"], (spec.get("cluster") or {}).get("name", ""))
        attempts.setdefault(key, []).append(backup)

    latest: dict[tuple[str, str], float] = {}
    failed: dict[tuple[str, str], str] = {}
    for key, items in attempts.items():
        items.sort(key=lambda b: b["metadata"].get("creationTimestamp", ""), reverse=True)

        # Most recent completed attempt drives the freshness check.
        for backup in items:
            if backup.get("status", {}).get("phase") == "completed":
                stamp = backup["status"].get("stoppedAt") or backup["metadata"].get("creationTimestamp", "")
                hours = age_hours(stamp)
                if hours is not None:
                    latest[key] = hours
                break

        # Most recent *settled* attempt decides whether backups are failing now.
        for backup in items:
            phase = backup.get("status", {}).get("phase", "")
            if phase in ("running", "started", "pending", ""):
                continue
            if phase != "completed":
                failed[key] = f"{backup['metadata']['name']} ({phase})"
            break

    covered = {(s["metadata"]["namespace"], (s.get("spec", {}).get("cluster") or {}).get("name", ""))
               for s in scheduled}

    rows: list[tuple[str, str, str]] = []
    problems = 0

    for cluster in sorted(clusters, key=lambda c: (c["metadata"]["namespace"], c["metadata"]["name"])):
        namespace = cluster["metadata"]["namespace"]
        name = cluster["metadata"]["name"]
        key = (namespace, name)
        label = f"{namespace}/{name}"

        if key not in covered:
            rows.append((label, "NO SCHEDULED BACKUP", "no ScheduledBackup targets this cluster"))
            print(f"::error title=Unprotected database::{label} has no ScheduledBackup")
            problems += 1
            continue

        if key in failed:
            rows.append((label, "FAILED", f"most recent attempt failed: {failed[key]}"))
            print(f"::error title=Backup failed::{label}: {failed[key]}")
            problems += 1
            continue

        if key not in latest:
            rows.append((label, "NO COMPLETED BACKUP", "scheduled, but nothing has completed yet"))
            print(f"::error title=No completed backup::{label} has never completed a backup")
            problems += 1
            continue

        hours = latest[key]
        if hours > max_age:
            rows.append((label, "STALE", f"newest completed backup is {hours:.1f}h old (limit {max_age:.0f}h)"))
            print(f"::error title=Stale backup::{label}: newest backup is {hours:.1f}h old")
            problems += 1
        else:
            rows.append((label, "ok", f"newest completed backup {hours:.1f}h old"))

    width = max((len(r[0]) for r in rows), default=10)
    print(f"\nCNPG backup check — context '{context}' (max age {max_age:.0f}h)\n")
    for label, state, detail in rows:
        print(f"  {label:<{width}}  {state:<20} {detail}")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as fh:
            fh.write(f"\n### CNPG backups — `{context}`\n\n")
            fh.write("| database | state | detail |\n| --- | --- | --- |\n")
            for label, state, detail in rows:
                fh.write(f"| `{label}` | {state} | {detail} |\n")

    print()
    if problems:
        print(f"check-backups: {problems} problem(s) in context '{context}'")
        return 1
    print(f"check-backups: all {len(rows)} databases protected and current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
