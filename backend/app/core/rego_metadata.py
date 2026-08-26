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

# Shared Rego helpers, not rules. They live under ``rules/`` because the OPA
# server loads exactly that directory (``opa/Dockerfile`` copies it to
# ``/policies``), so a helper package outside it would not resolve for the
# ``import data.greensecops.lib.*`` in every rule that uses one. They are not
# rules, though: they carry no METADATA, declare no severity and emit no
# ``violations``, so every consumer of ``iter_rule_files`` — the DB seed, the
# docs generator, the example validators, the catalog tests — has to skip them.
# Excluding them here rather than in each caller keeps the four in agreement.
LIB_DIR = "lib"

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


# The names the backend binds each expression to when it sends the query to
# OPA's `/v1/query`. Callers that need the bindings wrap the expressions
# themselves — see `domain_violations_expr`.
VIOLATIONS_BINDING = "violations"
PACKAGES_BINDING = "rules"


def domain_violations_expr(domain: str) -> str:
    """The Rego comprehension collecting every violation one domain can raise.

    ``greensecops.<domain>.<category>.<rule>.violations``, flattened. This is
    the query shape that lets a whole domain be evaluated in **one** call
    instead of one call per rule, and it lives here so the backend evaluator
    and ``scripts/opa_eval.py`` cannot drift apart on which rules an engine is
    graded against.

    It is deliberately the bare expression, not a complete query, because the
    two callers submit it over transports with different conventions:

    * ``opa eval -f raw`` evaluates a bare expression and prints its value.
    * OPA's ``/v1/query`` returns *variable bindings*, so an unbound
      comprehension evaluates to ``{"result": [{}]}`` — successful, and
      carrying no violations at all. The backend therefore binds it to
      ``VIOLATIONS_BINDING`` first.

    That second point is why this returns an expression rather than a query: a
    single shared string would silently report a clean scan on one of the two.

    Per-domain rather than one cross-domain aggregate, because rules in other
    domains fire on negations (a ci_workflow rule asking ``not input.name``)
    that are vacuously true for a Terraform or Docker document.
    """
    return f"[v | v := data.greensecops.{domain}[_][_].violations[_]]"


def domain_packages_expr(domain: str) -> str:
    """The names of the rule packages OPA currently has loaded for ``domain``.

    Companion to `domain_violations_expr`, and the reason the backend can send
    one query instead of two. A domain whose bundle is missing answers a
    violation query *identically* to a spotless document — both come back as
    ``{"result": [{"violations": []}]}`` — so the violations alone cannot tell
    "nothing is wrong" from "nothing was checked". Asking for the inventory in
    the same query settles it: a loaded domain names its packages, an absent
    one returns an empty list.

    The names include each rule's ``_test`` package, because the policy server
    loads the whole rules directory. That makes this an existence check, not a
    count to reconcile against the files on disk.
    """
    return f"[r | data.greensecops.{domain}[_][r]]"


def iter_rule_files(rules_dir: Path | None = None) -> Iterator[Path]:
    """Yield every policy ``.rego`` under ``rules_dir``, tests and helpers excluded.

    Sorted so callers get a stable order — seeding, docs generation and the
    validators all report per-rule problems, and a stable order keeps their
    output diffable.

    Anything under ``lib/`` is a shared helper rather than a rule; see
    ``LIB_DIR``.
    """
    base = RULES_DIR if rules_dir is None else rules_dir
    for path in sorted(base.glob("**/*.rego")):
        if path.name.endswith(_TEST_SUFFIX):
            continue
        if LIB_DIR in path.relative_to(base).parts:
            continue
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
