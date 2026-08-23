"""Locate rule files and lift the ``# METADATA`` block out of them.

Deliberately dependency-free — stdlib only, no ``app`` imports, no YAML
library. Three separate Python environments need this logic and none of them
share a dependency set: the backend (seeds the ``rule`` table from it), the
Sphinx docs project (``docs/pyproject.toml`` has only sphinx + pyyaml), and the
CI validation scripts (``.github/workflows/opa.yml`` installs only
ruamel.yaml + python-hcl2). Each had grown its own copy of the same line
scanner.

So this module stops at the boundary where the environments diverge: it returns
the block's **raw YAML text**, and each caller parses it with the loader it
already has. The part worth sharing is the scanning — knowing that a block
starts at a line that is exactly ``# METADATA``, that ``# `` is stripped from
each following line, that a bare ``#`` is a blank line, and that the first line
which is neither ends the block.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

# app/core/rego_metadata.py -> app/rules
RULES_DIR = Path(__file__).resolve().parents[1] / "rules"

_METADATA_MARKER = "# METADATA"
_TEST_SUFFIX = "_test.rego"

# Worst first, for any report that lists rules or violations in the order a
# reader should act on them. Declared here rather than derived from
# ``models.enums.Severity`` for the same reason as everything else in this
# module: the docs and CI environments cannot import the models. The two must
# agree, and ``tests/core/test_rego_metadata.py`` asserts that they do.
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def severity_rank(severity: str) -> int:
    """Sort key for ``severity``; anything unrecognised sorts last so an
    unannotated rule never masks a real critical."""
    return SEVERITY_ORDER.get(severity, len(SEVERITY_ORDER))


def iter_rule_files(rules_dir: Path | None = None) -> Iterator[Path]:
    """Yield every policy ``.rego`` under ``rules_dir``, tests excluded.

    Sorted so callers get a stable order — seeding, docs generation and the
    validators all report per-rule problems, and a stable order keeps their
    output diffable.
    """
    base = RULES_DIR if rules_dir is None else rules_dir
    for path in sorted(base.glob("**/*.rego")):
        if not path.name.endswith(_TEST_SUFFIX):
            yield path


def extract_metadata_block(content: str) -> str | None:
    """Return the raw YAML text of the first ``# METADATA`` block, or None.

    ``None`` means the file has no annotation at all, which callers treat as an
    error rather than a default — an unannotated rule has no severity, so it
    cannot be catalogued.
    """
    lines: list[str] = []
    in_block = False

    for line in content.splitlines():
        if not in_block:
            if line.rstrip() == _METADATA_MARKER:
                in_block = True
            continue
        if line.startswith("# "):
            lines.append(line[2:])
        elif line.rstrip() == "#":
            lines.append("")
        else:
            break

    if not lines:
        return None
    return "\n".join(lines)


def read_metadata_block(path: Path) -> str | None:
    """``extract_metadata_block`` for a file on disk."""
    return extract_metadata_block(path.read_text(encoding="utf-8"))
