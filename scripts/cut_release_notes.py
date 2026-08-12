#!/usr/bin/env python3
"""Close off the "Latest Changes" section of release-notes.md as a release.

``.github/workflows/latest-changes.yml`` accumulates one bullet per merged pull
request under a ``## Latest Changes`` heading. Cutting a release means giving
that pile a version and a date, and opening a fresh empty pile above it:

    ## Latest Changes              ->     ## Latest Changes

    ### Features                          ## 0.11.0 (2026-08-12)
    * feat(api): ...
                                          ### Features
    ## 0.10.0 (2026-01-23)                * feat(api): ...

                                          ## 0.10.0 (2026-01-23)

The section that was cut is also written out verbatim, because it is exactly
the body the GitHub release draft should carry — deriving it twice, once here
and once from a `git log` in the workflow, is how the two end up disagreeing.

This supersedes ``scripts/add_latest_release_date.py``, which dated a header
that had already been renamed by hand. Setting the version and the date in one
step removes the window in which the header exists without a date, which is
what that script was there to catch.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_NOTES = ROOT / "release-notes.md"

LATEST_CHANGES_HEADER = "## Latest Changes"

# Any `## ` heading, which is what bounds a release section. The subsections
# latest-changes.yml writes are `### `, so they are not matched.
SECTION_HEADER = re.compile(r"^## ", re.MULTILINE)

# A released section's heading. Accepts a pre-release suffix (0.11.0-rc1) —
# release.yml takes an explicit version precisely so a candidate can be cut,
# and a pattern that only matched X.Y.Z would silently fail to find the section
# it had just written.
RELEASE_HEADER_PATTERN = re.compile(
    r"^## (\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)\s*(\(.*\))?\s*$",
    re.MULTILINE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="The version being released, e.g. 0.11.0.")
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Release date as YYYY-MM-DD. Defaults to today.",
    )
    parser.add_argument(
        "--body-file",
        type=Path,
        help="Write the cut section's body here, for the release draft.",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Permit cutting a release with no accumulated changes.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    text = RELEASE_NOTES.read_text(encoding="utf-8")

    start = text.find(f"{LATEST_CHANGES_HEADER}\n")
    if start == -1:
        print(
            f"release-notes.md has no {LATEST_CHANGES_HEADER!r} heading, so "
            "there is nothing to cut. latest-changes.yml writes under that "
            "exact heading — if it moved, both need updating together.",
            file=sys.stderr,
        )
        return 1

    already = RELEASE_HEADER_PATTERN.search(text)
    if already and already.group(1) == args.version:
        print(
            f"release-notes.md already has a {args.version} section. Refusing "
            "to cut it twice.",
            file=sys.stderr,
        )
        return 1

    body_start = start + len(f"{LATEST_CHANGES_HEADER}\n")
    next_section = SECTION_HEADER.search(text, body_start)
    body_end = next_section.start() if next_section else len(text)
    body = text[body_start:body_end].strip()

    if not body and not args.allow_empty:
        print(
            "There are no accumulated changes under "
            f"{LATEST_CHANGES_HEADER!r}, so this release would have empty "
            "notes. Pass --allow-empty if that is deliberate.",
            file=sys.stderr,
        )
        return 1

    released_header = f"## {args.version} ({args.date})"
    replacement = f"{LATEST_CHANGES_HEADER}\n\n{released_header}\n"
    updated = text[:start] + replacement + text[body_start:]
    RELEASE_NOTES.write_text(updated, encoding="utf-8")

    if args.body_file:
        args.body_file.write_text(f"{body}\n" if body else "", encoding="utf-8")

    entries = len([line for line in body.splitlines() if line.startswith("* ")])
    print(f"Cut {released_header.removeprefix('## ')} — {entries} entry(ies) ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
