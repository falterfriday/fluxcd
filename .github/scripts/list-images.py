#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

import yaml

def walk(node, out: set[str]) -> None:
    if isinstance(node, list):
        for item in node:
            walk(item, out)
        return
    if not isinstance(node, dict):
        return

    image = node.get("image")

    if isinstance(image, str) and ":" in image and not image.startswith("ENC["):
        out.add(image)

    if isinstance(image, dict):
        repo = image.get("repository")
        tag = image.get("tag")
        registry = image.get("registry")
        if repo and tag:
            prefix = f"{registry}/" if registry else ""
            out.add(f"{prefix}{repo}:{tag}")

    for value in node.values():
        walk(value, out)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2

    images: set[str] = set()
    for manifest in sorted(Path(sys.argv[1]).glob("*.yaml")):
        for doc in yaml.safe_load_all(manifest.read_text()):
            walk(doc, images)

    for image in sorted(images):
        print(image)
    return 0


if __name__ == "__main__":
    sys.exit(main())
