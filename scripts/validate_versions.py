#!/usr/bin/env python3
"""Assert every project manifest agrees with the root VERSION file.

The version is written down in six places — ``VERSION`` plus five derived ones
— and the two lockfiles record two of them again. ``scripts/bump_version.py``
sets them together; this proves they stayed together.

Drift here is quiet in the worst way. A stale ``frontend/package.json`` makes
``bun ci`` abort on a frozen-lockfile mismatch in the *production dashboard
build*, and a stale ``backend/app/__version__.py`` makes the dashboard footer
and the API's ``/version/`` endpoint disagree about what is deployed — which is
precisely the question that endpoint exists to answer.

The check is a whitelist, not a walk. Three manifests deliberately carry no
version at all (a bun workspace root, a uv workspace root, and the static
landing site), and a glob-and-assert implementation would either fail on them
or, worse, "fix" them into a sixth source of truth. Their versionlessness is
asserted just as explicitly as the others' values.
"""

from __future__ import annotations

import sys

from _versions import (
    ROOT,
    TARGETS,
    VERSIONLESS,
    VERSIONLESS_PATTERNS,
    read_version,
)


def main() -> int:
    version = read_version()
    errors: list[str] = []

    for target in TARGETS:
        if not target.path.exists():
            errors.append(f"{target.relative_path} does not exist.")
            continue

        declared = target.read()
        if declared is None:
            errors.append(
                f"{target.relative_path} declares no version. It should be "
                f"{version!r} — run `python scripts/bump_version.py {version}`."
            )
        elif declared != version:
            errors.append(
                f"{target.relative_path} is at {declared!r}, but VERSION says "
                f"{version!r}. Run `python scripts/bump_version.py {version}`."
            )

    for relative_path in VERSIONLESS:
        path = ROOT / relative_path
        if not path.exists():
            continue
        if VERSIONLESS_PATTERNS[relative_path].search(path.read_text(encoding="utf-8")):
            errors.append(
                f"{relative_path} has grown a version key. It is a workspace "
                "root or an unpublished member, so a version there is a sixth "
                "source of truth nothing propagates to — remove it, or add it "
                "to TARGETS in scripts/_versions.py if it really should track "
                "VERSION."
            )

    if errors:
        print("Version validation FAILED:\n", file=sys.stderr)
        for error in errors:
            print(f"  ✗ {error}\n", file=sys.stderr)
        return 1

    print(f"All {len(TARGETS)} manifest(s) agree with VERSION ({version}) ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
