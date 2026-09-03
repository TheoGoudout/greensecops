#!/usr/bin/env python3
"""Check that no workflow or composite action carries an embedded script, and that
.github/scripts/ agrees with them.

Shell inside a YAML string is invisible to every linter there is. Moving each
step body into .github/scripts/ is what lets the shellcheck hook see it at all
— so the convention has to hold, or it decays one pull request at a time. This
is the guard that stops that, in the style of the other drift checks beside it.

Four things are asserted:

1. No workflow or composite action has a multi-line ``run:``. A ``script:`` block (actions/
   github-script) is allowed only as a one-line ``require(...)`` loader.
2. Every ``.github/scripts/`` path one of them names exists on disk.
3. Every script under ``.github/scripts/`` is named by one of them — which
   catches the orphan a workflow edit leaves behind.

``.github/scripts/lib/`` is exempt from (3) and (4): it is sourced by other
scripts rather than invoked by a step, so no workflow names it and it carries
no shebang.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / ".github" / "scripts"
WORKFLOW_DIRS = (
    ROOT / ".github" / "workflows",
    ROOT / "action" / ".github" / "workflows",
)
# Composite actions carry step bodies exactly as workflows do, and are just as
# invisible to shellcheck when that body is a YAML string — so they are held to
# the same rule, and their `.github/scripts/` references count as calls.
ACTION_FILES = tuple(sorted((ROOT / ".github" / "actions").glob("*/action.yml")))

# A step body written as a YAML block scalar: `run: |`, `run: >-`, and so on.
BLOCK = re.compile(r"^(\s*)(run|script):\s*[|>][+-]?\s*$")
# Any .github/scripts/ path mentioned anywhere in a workflow. The last
# character may not be a `.`, so a sentence ending "see .github/scripts/
# README.md." does not resolve to a filename with the full stop attached.
REFERENCE = re.compile(r"\.github/scripts/[\w./-]*[\w/-]")
# The one shape of `script:` block that is allowed to survive: a loader.
LOADER = re.compile(r"require\(.*\)")

SHEBANG = "#!/usr/bin/env bash"


def workflows() -> list[Path]:
    files = [p for d in WORKFLOW_DIRS if d.is_dir() for p in d.glob("*.yml")]
    return sorted(files) + list(ACTION_FILES)


def destination(wf: Path) -> str:
    """The .github/scripts/ subdirectory a file's step bodies belong in."""
    return wf.parent.name if wf.name == "action.yml" else wf.stem


def block_body(lines: list[str], start: int, indent: int) -> tuple[list[str], int]:
    """The lines of the block opened at `start`, and the index after it."""
    body, i = [], start + 1
    while i < len(lines):
        line = lines[i]
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line)
        i += 1
    return [b for b in body if b.strip()], i


def jobs_missing_checkout(wf: Path) -> list[str]:
    """Names of jobs that run a .github/scripts/ path without checking out."""
    doc = yaml.safe_load(wf.read_text()) or {}
    missing = []
    for name, job in (doc.get("jobs") or {}).items():
        steps = job.get("steps") or []
        if any("actions/checkout" in str(s.get("uses", "")) for s in steps):
            continue
        if any(
            "/scripts/" in str(s.get("run", ""))
            or "/scripts/" in str((s.get("with") or {}).get("script", ""))
            for s in steps
        ):
            missing.append(name)
    return missing


def main() -> int:
    errors: list[str] = []
    referenced: set[Path] = set()

    for wf in workflows():
        rel = wf.relative_to(ROOT)
        lines = wf.read_text().split("\n")
        i = 0
        while i < len(lines):
            match = BLOCK.match(lines[i])
            if not match:
                i += 1
                continue
            indent, key = len(match.group(1)), match.group(2)
            body, i = block_body(lines, i, indent)
            if key == "run":
                errors.append(
                    f"{rel}:{i - len(body)}: a multi-line `run:` block of {len(body)} line(s). "
                    f"Move it to .github/scripts/{destination(wf)}/<step>.sh and call it from here — "
                    f"see .github/scripts/README.md."
                )
            elif len(body) != 1 or not LOADER.search(body[0]):
                errors.append(
                    f"{rel}:{i - len(body)}: a multi-line `script:` block. The only body a "
                    f"github-script step may carry is a one-line require() of a file under "
                    f".github/scripts/."
                )

        for job in jobs_missing_checkout(wf):
            errors.append(
                f"{rel}: job '{job}' runs a script from .github/scripts/ but never checks "
                f"the repository out, so the file will not be there. Add an "
                f"actions/checkout step (and `contents: read` to its permissions)."
            )

        for path in REFERENCE.findall(wf.read_text()):
            target = ROOT / path
            referenced.add(target)
            if not target.exists():
                errors.append(f"{rel}: names {path}, which does not exist.")

    for script in sorted(SCRIPTS.rglob("*")):
        if not script.is_file() or script.name == "README.md":
            continue
        rel = script.relative_to(ROOT)
        if SCRIPTS / "lib" in script.parents:
            continue
        if script not in referenced:
            errors.append(
                f"{rel}: no workflow or composite action calls this. "
                f"Delete it, or wire it up."
            )
        first = script.read_text().split("\n", 1)[0]
        if script.suffix == ".sh" and first != SHEBANG:
            errors.append(f"{rel}: starts with {first!r}, expected {SHEBANG!r}.")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
