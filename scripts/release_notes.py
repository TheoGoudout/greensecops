#!/usr/bin/env python3
"""Write a release's notes from the pull requests merged since the last one.

The notes are generated once, when ``.github/workflows/release-prepare.yml`` cuts the
release, and used twice: prepended to ``release-notes.md`` as
``## X.Y.Z (date)``, and written verbatim to ``--body-file`` as the body of the
GitHub release draft. Deriving them once is what keeps the two from
disagreeing.

The range is the first-parent history from the most recent *stable* tag to
``HEAD``, so a stable release's notes cover everything since the last stable
release rather than only the delta since its own release candidate. Each merge
names its pull request (``Merge pull request #N`` or a squash's ``(#N)``);
commits that name none, like the release bump itself, are not changes to
report. The pull request's labels pick its section: ``labeler.yml`` requires
one on every pull request, and ``SECTIONS`` below maps them to headings.

This file is the same in every repository that releases this way; change it
in all of them together.

Usage:

    scripts/release_notes.py 0.13.0 --body-file body.md
    scripts/release_notes.py 0.13.0 --from v0.12.0 --dry-run

Pull requests are read with ``gh api``, so ``gh`` must be authenticated
(``GH_TOKEN`` in CI) and the repository is taken from ``GITHUB_REPOSITORY``
unless ``--repo`` names it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_NOTES = ROOT / "release-notes.md"

# Label -> heading, in the order the sections appear. These are the headings
# tiangolo/latest-changes uses, which older release-notes.md sections were
# written with.
SECTIONS: list[tuple[str, str]] = [
    ("breaking", "Breaking Changes"),
    ("security", "Security Fixes"),
    ("feature", "Features"),
    ("bug", "Fixes"),
    ("refactor", "Refactors"),
    ("upgrade", "Upgrades"),
    ("docs", "Docs"),
    ("lang-all", "Translations"),
    ("internal", "Internal"),
]
# A pull request with none of the labels above still shipped; it is listed
# rather than dropped.
UNLABELLED = "Internal"

STABLE_TAG = re.compile(r"^v\d+\.\d+\.\d+$")
MERGE_SUBJECT = re.compile(r"^Merge pull request #(\d+)\b")
SQUASH_SUBJECT = re.compile(r"\(#(\d+)\)\s*$")

# A released section's heading. Accepts a pre-release suffix (0.11.0-rc1),
# which release-prepare.yml can cut from an explicit version.
RELEASE_HEADER = re.compile(
    r"^## (\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)\s*(\(.*\))?\s*$",
    re.MULTILINE,
)
SECTION_HEADER = re.compile(r"^## ", re.MULTILINE)
LATEST_CHANGES_HEADER = "## Latest Changes"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="The version being released, e.g. 0.13.0.")
    parser.add_argument(
        "--from",
        dest="from_ref",
        help="Start of the range. Defaults to the most recent stable tag.",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="owner/name to read pull requests from. Defaults to $GITHUB_REPOSITORY.",
    )
    parser.add_argument(
        "--date",
        default=datetime.now(tz=UTC).date().isoformat(),
        help="Release date as YYYY-MM-DD. Defaults to today, in UTC.",
    )
    parser.add_argument(
        "--body-file",
        type=Path,
        help="Write the notes' body here, for the release draft.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the section instead of writing release-notes.md.",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Permit a release with no merged pull requests.",
    )
    return parser.parse_args()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def last_stable_tag() -> str | None:
    """The most recent vX.Y.Z tag reachable from HEAD, skipping pre-releases."""
    for tag in git(
        "tag", "--merged", "HEAD", "--list", "v*", "--sort=-v:refname"
    ).split():
        if STABLE_TAG.match(tag):
            return tag
    return None


def merged_pull_requests(from_ref: str | None) -> list[int]:
    """Pull request numbers merged into HEAD since from_ref, newest first."""
    rev = f"{from_ref}..HEAD" if from_ref else "HEAD"
    numbers: list[int] = []
    for subject in git("log", "--first-parent", "--format=%s", rev).splitlines():
        match = MERGE_SUBJECT.match(subject) or SQUASH_SUBJECT.search(subject)
        if match and int(match.group(1)) not in numbers:
            numbers.append(int(match.group(1)))
    return numbers


def fetch_pull_request(repo: str, number: int) -> dict[str, object]:
    out = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{repo}/pulls/{number}",
            "--jq",
            (
                "{title, url: .html_url, labels: [.labels[].name],"
                " login: .user.login, user_url: .user.html_url}"
            ),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    data: dict[str, object] = json.loads(out)
    return data


def entry(number: int, pr: dict[str, object]) -> str:
    title = str(pr["title"]).strip().rstrip(".")
    return (
        f"* {title}. PR [#{number}]({pr['url']}) by [@{pr['login']}]({pr['user_url']})."
    )


def render(repo: str, numbers: list[int]) -> str:
    grouped: dict[str, list[str]] = {heading: [] for _, heading in SECTIONS}
    for number in numbers:
        pr = fetch_pull_request(repo, number)
        labels = pr["labels"]
        assert isinstance(labels, list)
        heading = next(
            (heading for label, heading in SECTIONS if label in labels), UNLABELLED
        )
        grouped[heading].append(entry(number, pr))
    blocks = [
        f"### {heading}\n\n" + "\n".join(lines)
        for heading, lines in grouped.items()
        if lines
    ]
    return "\n\n".join(blocks)


def drop_latest_changes(text: str) -> str:
    """Remove a ``## Latest Changes`` section, as tiangolo/latest-changes writes.

    Every entry in it is a merged pull request this script lists again, so it
    is dropped rather than released twice. A repository that never ran that
    action has no such section, and this does nothing.
    """
    start = text.find(f"{LATEST_CHANGES_HEADER}\n")
    if start == -1:
        return text
    end = SECTION_HEADER.search(text, start + len(LATEST_CHANGES_HEADER))
    return text[:start] + (text[end.start() :] if end else "")


def insert(text: str, section: str) -> str:
    """Put the new section above the newest existing one."""
    text = drop_latest_changes(text)
    first = SECTION_HEADER.search(text)
    at = first.start() if first else len(text)
    head = text[:at].rstrip("\n")
    return f"{head}\n\n{section}\n\n{text[at:]}".rstrip("\n") + "\n"


def main() -> int:
    args = parse_args()
    if not args.repo:
        print("No repository: pass --repo or set GITHUB_REPOSITORY.", file=sys.stderr)
        return 1

    text = RELEASE_NOTES.read_text(encoding="utf-8")
    if any(m.group(1) == args.version for m in RELEASE_HEADER.finditer(text)):
        print(
            f"release-notes.md already has a {args.version} section. Refusing "
            "to write it twice.",
            file=sys.stderr,
        )
        return 1

    from_ref = args.from_ref or last_stable_tag()
    numbers = merged_pull_requests(from_ref)
    if not numbers and not args.allow_empty:
        print(
            f"No pull request was merged since {from_ref or 'the first commit'}, "
            "so this release would have empty notes. Pass --allow-empty if that "
            "is deliberate.",
            file=sys.stderr,
        )
        return 1

    body = render(args.repo, numbers)
    section = f"## {args.version} ({args.date})"
    if body:
        section += f"\n\n{body}"

    if args.dry_run:
        print(section)
    else:
        RELEASE_NOTES.write_text(insert(text, section), encoding="utf-8")
    if args.body_file:
        args.body_file.write_text(f"{body}\n" if body else "", encoding="utf-8")

    print(
        f"Wrote {args.version} — {len(numbers)} pull request(s) since "
        f"{from_ref or 'the first commit'} ✅",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
