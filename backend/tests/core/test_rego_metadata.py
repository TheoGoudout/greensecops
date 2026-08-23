"""Constraints on ``app.core.rego_metadata`` that other environments rely on.

Three Python environments import this module and none of them share a
dependency set: the backend, the Sphinx docs project (sphinx + pyyaml) and the
CI validation scripts (ruamel.yaml + python-hcl2). Two of them get at it
without installing the app at all — ``docs/Dockerfile`` copies just this file
and its package markers, and ``scripts/opa_eval.py`` adds ``backend/`` to
``sys.path``.

That only works while the module stays stdlib-only, which nothing in the
module itself can enforce. These tests do.
"""

import ast
import sys
from pathlib import Path

from app.core import rego_metadata
from app.core.rego_metadata import SEVERITY_ORDER, iter_rule_files
from app.models.enums import Severity

_MODULE_PATH = Path(rego_metadata.__file__)


def _imported_roots(path: Path) -> set[str]:
    """Top-level module names ``path`` imports, at module scope or inside it."""
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_imports_only_the_standard_library() -> None:
    """No third-party and no ``app`` imports.

    A new import here breaks the docs image build and the CI validators, and it
    breaks them at *their* build time rather than in any backend test — which
    is precisely why this assertion lives here.
    """
    third_party = _imported_roots(_MODULE_PATH) - set(sys.stdlib_module_names)
    assert third_party == set(), (
        f"rego_metadata must stay stdlib-only, but imports {sorted(third_party)}. "
        "docs/Dockerfile copies this file alone, without the app or its deps."
    )


def test_is_self_contained_within_the_app_package() -> None:
    """It must not reach into sibling modules, even relatively."""
    tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
    relative = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level > 0
    ]
    assert relative == [], "rego_metadata must not import from sibling app modules"


def test_severity_order_matches_the_issue_severity_enum() -> None:
    """``SEVERITY_ORDER`` is a hand-written copy of the enum's declaration
    order, because the docs and CI environments cannot import the models. If
    the enum ever gains or reorders a severity, this catches the drift."""
    assert list(SEVERITY_ORDER) == [s.value for s in Severity]
    assert list(SEVERITY_ORDER.values()) == list(range(len(Severity)))


def test_finds_every_shipped_rule_excluding_tests() -> None:
    found = list(iter_rule_files())
    assert found, "no .rego rules discovered"
    assert not any(p.name.endswith("_test.rego") for p in found)
    assert found == sorted(found), "order must be stable for diffable output"
