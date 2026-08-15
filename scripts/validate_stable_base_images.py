#!/usr/bin/env python3
"""Fail if any shipped Dockerfile pins a prerelease base image.

Dependabot cannot be trusted to keep prereleases out on its own. On 2026-08-13
it opened #215 proposing ``python:3.14.6-slim -> python:3.15.0b4-slim``,
seventeen minutes *after* ``.github/dependabot.yml`` had already grown an
``ignore: python >=3.15.0-0`` rule intended to stop exactly that. The ignore did
not hold, and neither did the docker updater's own prerelease filter.

Nor can the config express the rule we actually want. A prerelease sorts *below*
the release it leads to, so any ``ignore.versions`` range wide enough to cover
``3.15.0b4`` also covers ``3.15.0`` final — blocking the stable release we do
want. That is why this check lives here instead: it is a property of the tree,
checked deterministically, rather than a request Dependabot may decline.

A prerelease base image is a real problem and not a style preference: the beta
above ships no cp315 wheels for ``psycopg-binary``, so the backend image fails
to build at all.

Scope: every Dockerfile Dependabot manages. ``examples/`` is excluded — those
are rule-suite fixtures with deliberately broken and insecure content (see
``examples/docker/README.md``), and asserting anything about their pins would
fight the tests that own them.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directories Dependabot's docker ecosystem covers, per .github/dependabot.yml.
# Kept as a literal list rather than globbed so that adding a Dockerfile without
# adding it to Dependabot is visible here as a gap.
MANAGED_DIRS = ("backend", "docs", "frontend", "landing", "opa")

# `FROM image:tag` and `COPY --from=image:tag`, digest and platform tolerated.
IMAGE_REF = re.compile(
    r"""(?:^\s*FROM\s+(?:--platform=\S+\s+)?|--from=)
        (?P<image>[\w.\-/]+(?::[\w.\-]+)?)""",
    re.IGNORECASE | re.MULTILINE | re.VERBOSE,
)

# Two shapes of prerelease marker, deliberately narrow so that ordinary variant
# suffixes (-slim, -alpine, -noble, -static, -bookworm) do not trip it:
#   1. glued to the number, PEP 440 style      3.15.0b4, 3.15.0a2, 3.15.0rc1
#   2. a separated, whole-word marker          1.2.3-alpha.1, 3.15-rc, :beta
PRERELEASE = re.compile(
    r"""\d(?:a|b|rc)\d                                        # 3.15.0b4
      | [-.:](?:alpha|beta|rc|pre|preview|dev|nightly
              |snapshot|canary|unstable)(?:[-._\d]|$)         # -rc.1, -beta
    """,
    re.IGNORECASE | re.VERBOSE,
)


def dockerfiles() -> list[Path]:
    found: list[Path] = []
    for directory in MANAGED_DIRS:
        found.extend(sorted((ROOT / directory).glob("Dockerfile*")))
    return found


def prerelease_pins(path: Path) -> list[tuple[int, str, str]]:
    """Return (line number, image reference, offending tag) for each bad pin."""
    findings = []
    text = path.read_text(encoding="utf-8")
    for match in IMAGE_REF.finditer(text):
        image = match.group("image")
        _, _, tag = image.partition(":")
        if not tag or not PRERELEASE.search(tag):
            continue
        line = text.count("\n", 0, match.start()) + 1
        findings.append((line, image, tag))
    return findings


def main() -> int:
    failures = []
    for path in dockerfiles():
        for line, image, tag in prerelease_pins(path):
            failures.append(f"{path.relative_to(ROOT)}:{line}: {image} (tag {tag!r})")

    if not failures:
        return 0

    print("Prerelease base image pinned:\n", file=sys.stderr)
    for failure in failures:
        print(f"  {failure}", file=sys.stderr)
    print(
        "\nBase images must pin a stable release — no alpha, beta or release\n"
        "candidate. If Dependabot proposed this, close its pull request rather\n"
        "than merging it; .github/dependabot.yml cannot filter prereleases\n"
        "without also blocking the stable release that follows them.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
