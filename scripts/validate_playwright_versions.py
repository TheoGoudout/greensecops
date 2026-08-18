#!/usr/bin/env python3
"""Fail if the Playwright image and `@playwright/test` disagree on a version.

Playwright refuses to launch when the client and the browser image are on
different versions — every shard dies in ``auth.setup.ts`` with ``Executable
doesn't exist at /ms-playwright/...``. That has happened once already (b895eeb),
because the two live in different Dependabot ecosystems: ``@playwright/test`` is
npm (``bun``, one ``bun.lock`` at the root) and
``mcr.microsoft.com/playwright:v<x.y.z>-noble`` is docker
(``frontend/Dockerfile.playwright``), so they arrive as two separate pull
requests, each red on its own until the other lands.

Merging the pair into one pull request was tried in #221 via a Dependabot
``multi-ecosystem-group`` and reverted: a ``multi-ecosystem-group`` silently
disables the ``groups`` block on the same entry, so every dependency in those
entries came out as its own pull request (#226-#231). GitHub's config validator
accepts the combination; it just does not honour it.

So the two halves stay in two pull requests, and this hook makes the window
between them loud instead of silent: whichever lands first turns the tree red
with the exact version to set, rather than leaving a green-looking commit whose
tests cannot start.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DOCKERFILE = ROOT / "frontend" / "Dockerfile.playwright"
MANIFESTS = (ROOT / "frontend" / "package.json", ROOT / "landing" / "package.json")

PACKAGE = "@playwright/test"

# FROM mcr.microsoft.com/playwright:v1.62.1-noble@sha256:...
IMAGE_TAG = re.compile(
    r"^\s*FROM\s+mcr\.microsoft\.com/playwright:v(?P<version>[\d.]+)",
    re.IGNORECASE | re.MULTILINE,
)


def image_version() -> str | None:
    match = IMAGE_TAG.search(DOCKERFILE.read_text(encoding="utf-8"))
    return match.group("version") if match else None


def package_version(manifest: Path) -> str | None:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    for section in ("devDependencies", "dependencies"):
        if PACKAGE in data.get(section, {}):
            return data[section][PACKAGE]
    return None


def main() -> int:
    found: dict[str, str | None] = {
        f"{DOCKERFILE.relative_to(ROOT)} (image tag)": image_version()
    }
    for manifest in MANIFESTS:
        found[f"{manifest.relative_to(ROOT)} ({PACKAGE})"] = package_version(manifest)

    missing = [source for source, version in found.items() if version is None]
    if missing:
        print("Could not read a Playwright version from:", file=sys.stderr)
        for source in missing:
            print(f"  {source}", file=sys.stderr)
        print(
            "\nThis check is now blind to a version mismatch. Fix the source above,\n"
            "or update scripts/validate_playwright_versions.py if the pin moved.",
            file=sys.stderr,
        )
        return 1

    if len(set(found.values())) == 1:
        return 0

    print("Playwright version mismatch:\n", file=sys.stderr)
    for source, version in found.items():
        print(f"  {version:<12} {source}", file=sys.stderr)
    print(
        "\nThe browser image and @playwright/test must be on the same version, or\n"
        "every test fails with \"Executable doesn't exist at /ms-playwright/...\".\n"
        "Dependabot bumps them in two separate pull requests — set the other half\n"
        "to match rather than merging only one.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
