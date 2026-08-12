"""Where the project's version is written down, and how to read it.

The root ``VERSION`` file is the single source of truth; every entry below is
derived from it by ``scripts/bump_version.py`` and asserted by
``scripts/validate_versions.py``. Both import this module so the list of places
a version lives exists exactly once.

Adding another home for the version means adding it here — and to
``VERSIONLESS``, if the point is that some manifest should *stay* versionless.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"

# Semantic versions, including pre-release and build metadata. Deliberately
# permissive about the suffix: release.yml accepts an explicit version so a
# release candidate can be cut without teaching the bump arithmetic about them.
SEMVER = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?"
    r"(?:\+(?P<build>[0-9A-Za-z.-]+))?$"
)


class Target:
    """One file carrying the version, and the pattern that finds it.

    ``pattern`` must have exactly one capturing group around the version
    itself, so the same expression both reads the current value and locates the
    span to rewrite.
    """

    def __init__(self, relative_path: str, pattern: str) -> None:
        self.path = ROOT / relative_path
        self.relative_path = relative_path
        self.pattern = re.compile(pattern, re.MULTILINE)

    def read(self) -> str | None:
        """The version this file currently declares, or None if absent."""
        match = self.pattern.search(self.path.read_text(encoding="utf-8"))
        return match.group(1) if match else None

    def write(self, version: str) -> bool:
        """Point this file at ``version``. True if the file changed."""
        original = self.path.read_text(encoding="utf-8")
        match = self.pattern.search(original)
        if match is None:
            raise SystemExit(
                f"{self.relative_path}: no version found matching "
                f"{self.pattern.pattern!r}. The file's shape changed — update "
                "scripts/_versions.py."
            )
        start, end = match.span(1)
        updated = original[:start] + version + original[end:]
        if updated == original:
            return False
        self.path.write_text(updated, encoding="utf-8")
        return True


# The derived homes. Anchored tightly on purpose: an unanchored
# `"version"` would also match a dependency's pin in some other manifest shape,
# and silently rewriting one of those would be far worse than failing loudly.
TARGETS = [
    Target("frontend/package.json", r'^  "version": "([^"]*)"'),
    Target("action/package.json", r'^  "version": "([^"]*)"'),
    Target("backend/pyproject.toml", r'^version = "([^"]*)"'),
    Target("docs/pyproject.toml", r'^version = "([^"]*)"'),
    Target("backend/app/__version__.py", r'^__version__ = "([^"]*)"'),
    # Generated, but committed — and it carries the version because
    # backend/app/main.py passes `version=` to FastAPI, so it lands in the
    # schema's `info.version` and openapi-ts writes it out here.
    #
    # The pre-commit hook that regenerates the client only fires on
    # `backend/app/**.py`, which a release does touch — but release.yml does not
    # run pre-commit, so without this the file would sit one version behind
    # until some unrelated pull request regenerated it and carried a confusing
    # stray diff. Rewriting it here keeps the release self-consistent; a
    # regeneration produces byte-identical output, since it reads the same
    # __version__.py two entries above.
    Target("frontend/src/client/core/OpenAPI.ts", r"^\s*VERSION: '([^']*)'"),
]

# Manifests that must stay versionless. The root two are a bun workspace root
# and a uv workspace root — neither is published, and giving either a version
# would create a source of truth that nothing propagates to. landing/ is
# a workspace member that ships as static HTML and has never carried one.
#
# Checked as explicitly as the targets: the failure this prevents is somebody
# adding `"version": "1.0.0"` to one of them and it quietly going stale.
VERSIONLESS = [
    "package.json",
    "pyproject.toml",
    "landing/package.json",
]

VERSIONLESS_PATTERNS = {
    "package.json": re.compile(r'^  "version":', re.MULTILINE),
    "pyproject.toml": re.compile(r"^version = ", re.MULTILINE),
    "landing/package.json": re.compile(r'^  "version":', re.MULTILINE),
}


def read_version() -> str:
    """The version the repository claims to be at."""
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not SEMVER.match(version):
        raise SystemExit(f"VERSION holds {version!r}, which is not a semantic version.")
    return version


def bump(version: str, part: str) -> str:
    """Apply a major/minor/patch bump, dropping any pre-release suffix.

    A bump off a pre-release resolves to the release it was heading for:
    0.11.0-rc1 patched is 0.11.0, not 0.11.1. That is what makes
    `--bump patch` the right way to promote a release candidate.
    """
    match = SEMVER.match(version)
    if match is None:
        raise SystemExit(f"{version!r} is not a semantic version.")

    major, minor, patch = (int(match.group(p)) for p in ("major", "minor", "patch"))
    was_prerelease = match.group("prerelease") is not None

    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return (
            f"{major}.{minor}.{patch}"
            if was_prerelease
            else f"{major}.{minor}.{patch + 1}"
        )
    raise SystemExit(f"Unknown bump part {part!r}. Use major, minor or patch.")
