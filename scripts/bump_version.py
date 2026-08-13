#!/usr/bin/env python3
"""Set the project's version everywhere it is written down.

The root ``VERSION`` file is the source of truth; this propagates it to every
place listed in ``scripts/_versions.py`` — the four project manifests,
``backend/app/__version__.py`` and the generated API client — then regenerates
``uv.lock``. ``scripts/validate_versions.py`` asserts the result.

**Regenerating uv.lock is not optional**, which is the whole reason this is a
script rather than a handful of `sed` calls in a workflow. ``uv.lock`` records
the version of the ``app`` and ``docs`` workspace members. The Docker builds use
``uv sync --frozen``, which does not verify and so survives a stale lock — but
``.github/workflows/pre-commit.yml`` runs ``uv sync --all-packages`` unfrozen,
silently relocks, and then commits the result onto the contributor's branch.
That commit touches ``uv.lock``, which trips guard-dependencies.yml and
auto-closes an outside contributor's pull request over a dependency change they
never made.

``bun.lock`` also records workspace member versions, but deliberately gets no
treatment here. Measured on bun 1.3.11: neither ``bun install`` nor
``bun install --frozen-lockfile`` (which is what ``bun ci`` runs) refreshes
those fields *or* validates them against the manifests, so they are inert — a
mismatch neither breaks an install nor produces a stray lockfile diff for
pre-commit.yml to commit. Rewriting them would mean hand-editing a lockfile to
fix something nothing reads. If a future bun starts enforcing it, the symptom
is a frozen-lockfile failure in CI and the fix belongs here.

Usage:

    scripts/bump_version.py 0.11.0        # explicit, including 0.11.0-rc1
    scripts/bump_version.py --bump minor  # computed from the VERSION file
    scripts/bump_version.py --bump minor --print-only   # resolve, change nothing
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

from _versions import SEMVER, TARGETS, VERSION_FILE, bump, read_version

# Regenerating a lockfile needs its package manager. Missing tools are reported
# together at the end rather than half-way through, so a local run without uv
# installed still tells you everything it could not do.
LOCK_COMMANDS = [
    ("uv", ["uv", "lock"], "uv.lock"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("version", nargs="?", help="The exact version to set.")
    group.add_argument(
        "--bump",
        choices=("major", "minor", "patch"),
        help="Derive the next version from the current VERSION file.",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print the resolved version and exit without writing anything.",
    )
    parser.add_argument(
        "--skip-locks",
        action="store_true",
        help="Do not regenerate uv.lock. For tests; a release must not use this.",
    )
    return parser.parse_args()


def regenerate_locks() -> int:
    """Relock. Returns the number of failures."""
    failures = 0
    for tool, command, lockfile in LOCK_COMMANDS:
        if shutil.which(tool) is None:
            print(
                f"  ✗ {lockfile}: {tool} is not installed, so it was NOT "
                f"regenerated. Run `{' '.join(command)}` before committing.",
                file=sys.stderr,
            )
            failures += 1
            continue

        print(f"  → {' '.join(command)}")
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            print(
                f"  ✗ {lockfile}: {' '.join(command)} failed:\n{result.stderr.strip()}",
                file=sys.stderr,
            )
            failures += 1
    return failures


def main() -> int:
    args = parse_args()

    if args.bump:
        version = bump(read_version(), args.bump)
    else:
        version = args.version.strip()
        if not SEMVER.match(version):
            print(
                f"{version!r} is not a semantic version (X.Y.Z, optionally "
                "-prerelease).",
                file=sys.stderr,
            )
            return 1

    if args.print_only:
        print(version)
        return 0

    print(f"Setting the version to {version}\n")

    VERSION_FILE.write_text(f"{version}\n", encoding="utf-8")
    print("  ✓ VERSION")

    for target in TARGETS:
        changed = target.write(version)
        print(f"  {'✓' if changed else '·'} {target.relative_path}")

    if args.skip_locks:
        print("\nSkipped the lockfile (--skip-locks).")
        return 0

    print("\nRegenerating the lockfile:")
    failures = regenerate_locks()
    if failures:
        print(
            f"\n{failures} lockfile(s) were not regenerated. Committing a "
            "stale uv.lock makes an unrelated pull request relock and trip "
            "guard-dependencies.yml — see this script's docstring.",
            file=sys.stderr,
        )
        return 1

    print(f"\nEverything is at {version} ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
