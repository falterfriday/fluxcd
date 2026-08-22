#!/usr/bin/env python3

from __future__ import annotations

import base64
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
LOCKFILE = REPO / ".github" / "chart-digests.json"
EXACT = re.compile(r"^v?\d+\.\d+\.\d+$")
UA = {"User-Agent": "fluxcd-ci-chart-digests/1.0"}


def http_get(url: str, headers: dict[str, str] | None = None, timeout: int = 30):
    request = urllib.request.Request(url, headers={**UA, **(headers or {})})
    return urllib.request.urlopen(request, timeout=timeout)


def registry_token(www_authenticate: str) -> str | None:
    """Follow a registry's Bearer challenge to get an anonymous pull token."""
    if not www_authenticate.lower().startswith("bearer "):
        return None
    params = dict(re.findall(r'(\w+)="([^"]*)"', www_authenticate))
    realm = params.pop("realm", None)
    if not realm:
        return None
    query = "&".join(f"{k}={urllib.parse.quote(v, safe=':/')}" for k, v in params.items())
    try:
        with http_get(f"{realm}?{query}") as response:
            body = json.load(response)
    except urllib.error.URLError:
        return None
    return body.get("token") or body.get("access_token")


def oci_digest(reference: str) -> str | None:
    """Resolve registry/repo:tag to its manifest digest, anonymously."""
    host, _, path = reference.partition("/")
    repo, _, tag = path.rpartition(":")
    url = f"https://{host}/v2/{repo}/manifests/{tag}"
    accept = ", ".join(
        [
            "application/vnd.oci.image.manifest.v1+json",
            "application/vnd.oci.image.index.v1+json",
            "application/vnd.docker.distribution.manifest.v2+json",
        ]
    )
    headers = {"Accept": accept}
    try:
        with http_get(url, headers) as response:
            return response.headers.get("Docker-Content-Digest")
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            return None
        token = registry_token(exc.headers.get("WWW-Authenticate", ""))
        if not token:
            return None
        try:
            with http_get(url, {**headers, "Authorization": f"Bearer {token}"}) as response:
                return response.headers.get("Docker-Content-Digest")
        except urllib.error.URLError:
            return None
    except urllib.error.URLError:
        return None


_index_cache: dict[str, dict] = {}


def helm_index_digest(repo_url: str, chart: str, version: str) -> str | None:
    """Read the sha256 a classic Helm repository publishes for a chart version."""
    index_url = repo_url.rstrip("/") + "/index.yaml"
    if index_url not in _index_cache:
        try:
            with http_get(index_url, timeout=60) as response:
                _index_cache[index_url] = yaml.safe_load(response.read()) or {}
        except (urllib.error.URLError, yaml.YAMLError):
            _index_cache[index_url] = {}
    entries = (_index_cache[index_url].get("entries") or {}).get(chart) or []
    for entry in entries:
        if str(entry.get("version")) == version:
            digest = entry.get("digest")
            return f"sha256:{digest}" if digest and not digest.startswith("sha256:") else digest
    return None


def collect(rendered: Path) -> tuple[dict[str, dict], list[str]]:
    """Return ({chart-key: {...}}, [unlockable descriptions])."""
    repos: dict[str, dict] = {}
    releases: dict[str, dict] = {}
    unlockable: list[str] = []

    for manifest in sorted(rendered.glob("*.yaml")):
        for doc in yaml.safe_load_all(manifest.read_text()):
            if not isinstance(doc, dict):
                continue
            kind = doc.get("kind")
            spec = doc.get("spec") or {}
            if kind == "HelmRepository":
                repos[doc["metadata"]["name"]] = {
                    "url": spec.get("url", ""),
                    "type": spec.get("type", "default"),
                }
            elif kind == "HelmRelease":
                chart_spec = (spec.get("chart") or {}).get("spec") or {}
                chart = chart_spec.get("chart")
                version = str(chart_spec.get("version") or "")
                source = (chart_spec.get("sourceRef") or {}).get("name", "")
                if not chart:
                    continue
                if not EXACT.match(version):
                    label = f"{chart} ({version or 'no version'})"
                    if label not in unlockable:
                        unlockable.append(label)
                    continue
                releases[f"{source}/{chart}:{version}"] = {
                    "source": source,
                    "chart": chart,
                    "version": version,
                }

    for key, entry in releases.items():
        repo = repos.get(entry["source"])
        entry["repository"] = repo["url"] if repo else ""
        entry["repository_type"] = repo["type"] if repo else "unknown"

    return releases, unlockable


def resolve(entry: dict) -> str | None:
    url = entry.get("repository", "")
    if entry.get("repository_type") == "oci" or url.startswith("oci://"):
        base = url.removeprefix("oci://").rstrip("/")
        return oci_digest(f"{base}/{entry['chart']}:{entry['version']}")
    if url:
        return helm_index_digest(url, entry["chart"], entry["version"])
    return None


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    update = "--update" in sys.argv
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2

    releases, unlockable = collect(Path(args[0]))
    locked = {}
    if LOCKFILE.exists():
        locked = json.loads(LOCKFILE.read_text()).get("charts", {})

    resolved: dict[str, str] = {}
    unresolved: list[str] = []
    for key, entry in sorted(releases.items()):
        digest = resolve(entry)
        if digest:
            resolved[key] = digest
        else:
            unresolved.append(key)

    mismatches: list[tuple[str, str, str]] = []
    added: list[str] = []
    for key, digest in resolved.items():
        if key not in locked:
            added.append(key)
        elif locked[key] != digest:
            mismatches.append((key, locked[key], digest))

    removed = [k for k in locked if k not in resolved and k not in unresolved]

    if update:
        payload = {
            "_comment": (
                "Content digests for exactly-pinned Helm charts. Regenerate with "
                "`.github/scripts/chart-digests.py <rendered-dir> --update` after an "
                "intentional chart bump. A mismatch in CI means a version already "
                "deployed here was republished upstream with different content."
            ),
            "charts": dict(sorted(resolved.items())),
        }
        LOCKFILE.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"chart-digests: wrote {len(resolved)} digests to {LOCKFILE.relative_to(REPO)}")
        for key in unresolved:
            print(f"  unresolved: {key}")
        return 0

    print(f"chart-digests: {len(resolved)} pinned charts resolved, "
          f"{len(unlockable)} on ranges, {len(unresolved)} unresolved")
    for label in unlockable:
        print(f"  range (cannot lock): {label}")
    for key in unresolved:
        print(f"  could not resolve digest: {key}")
    for key in added:
        print(f"  NEW (not in lockfile): {key} -> {resolved[key]}")
    for key in removed:
        print(f"  no longer used: {key}")

    if mismatches:
        print()
        for key, expected, actual in mismatches:
            message = (
                f"{key} changed content upstream: lockfile has {expected}, "
                f"registry now serves {actual}"
            )
            print(f"  MISMATCH: {message}")
            print(f"::error title=Chart digest mismatch::{message}")
        return 1

    # A chart version appearing for the first time is normal — it is what a
    # chart bump looks like. Only a *changed* digest for a version already in
    # the lockfile indicates upstream republished content under a used tag, so
    # that is the one that blocks.
    if added:
        print()
        print("::warning title=Chart digest lockfile out of date::"
              f"{len(added)} pinned chart(s) missing from .github/chart-digests.json — "
              "run `.github/scripts/chart-digests.py <rendered-dir> --update` to record them")

    print("chart-digests: all pinned charts match the lockfile")
    return 0


if __name__ == "__main__":
    import urllib.parse  # noqa: E402  (used by registry_token)
    sys.exit(main())
