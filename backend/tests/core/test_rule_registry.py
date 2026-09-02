"""Tests for deriving the Rule catalog from the shipped Rego policies.

Two halves. The first drives ``rule_from_path`` over synthetic files to pin the
error behaviour — the module's whole point is that a malformed rule fails loudly
instead of quietly not existing, so the raising is the feature under test. The
second runs the real catalog and asserts the invariants a rule has to satisfy to
be shippable, which is what makes adding a rule a two-file operation: get these
wrong and the seed fails in CI rather than in production.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.rego_metadata import (
    RULES_DIR,
    extract_metadata_block,
    iter_rule_files,
)
from app.core.rule_registry import (
    VALID_DETECTION_METHODS,
    RuleMetadataError,
    discover_rules,
    rule_from_path,
)
from app.models import Category, RuleDomain, Severity

_VALID_METADATA = """\
# METADATA
# title: Example rule
# description: A rule used only by the registry tests.
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     fix: |
#       Do the thing the rule asks for.
package greensecops.ci_workflow.security.example

import rego.v1
"""


def _write(
    tmp_path: Path, body: str, rel: str = "ci_workflow/security/example.rego"
) -> Path:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# ─── extract_metadata_block ──────────────────────────────────────────────────


def test_extract_metadata_block_stops_at_the_package_line() -> None:
    block = extract_metadata_block(_VALID_METADATA)
    assert block is not None
    assert block.startswith("title: Example rule")
    assert "package" not in block


def test_extract_metadata_block_treats_a_bare_hash_as_a_blank_line() -> None:
    block = extract_metadata_block("# METADATA\n# title: T\n#\n# description: D\n")
    assert block == "title: T\n\ndescription: D"


def test_extract_metadata_block_returns_none_without_a_block() -> None:
    assert extract_metadata_block("package greensecops.a.b.c\n") is None


# ─── rule_from_path error paths ──────────────────────────────────────────────


def test_rule_from_path_reads_every_field(tmp_path: Path) -> None:
    rule = rule_from_path(_write(tmp_path, _VALID_METADATA), tmp_path)
    assert rule == {
        "slug": "example",
        "domain": RuleDomain.ci_workflow,
        "category": Category.security,
        "severity": Severity.high,
        # No custom.severity_weight, so the default for `high` applies.
        "severity_weight": 1.8,
        "title": "Example rule",
        "description": "A rule used only by the registry tests.",
        "remediation": "Do the thing the rule asks for.",
    }


def test_rule_from_path_honours_an_explicit_weight(tmp_path: Path) -> None:
    body = _VALID_METADATA.replace(
        "#   severity: high", "#   severity: high\n#   severity_weight: 2.0"
    )
    assert rule_from_path(_write(tmp_path, body), tmp_path)["severity_weight"] == 2.0


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        pytest.param(
            lambda body: body.replace("# METADATA\n", ""),
            "no '# METADATA' block",
            id="no-metadata",
        ),
        pytest.param(
            lambda body: body.replace("#   severity: high\n", ""),
            "no 'custom.severity'",
            id="no-severity",
        ),
        pytest.param(
            lambda body: body.replace("severity: high", "severity: catastrophic"),
            "not an Severity",
            id="bad-severity",
        ),
        pytest.param(
            lambda body: body.replace("#   detection: static_analysis\n", ""),
            "'custom.detection'",
            id="no-detection",
        ),
        pytest.param(
            lambda body: body.replace("detection: static_analysis", "detection: vibes"),
            "'custom.detection'",
            id="bad-detection",
        ),
        pytest.param(
            lambda body: body.replace("# title: Example rule\n", ""),
            "no 'title'",
            id="no-title",
        ),
        pytest.param(
            lambda body: body.replace(
                "# description: A rule used only by the registry tests.\n", ""
            ),
            "no 'description'",
            id="no-description",
        ),
        pytest.param(
            lambda body: body.replace("# title: Example rule", "# title: " + "x" * 300),
            "max 255",
            id="title-too-long",
        ),
        pytest.param(
            lambda body: body.replace(
                "#   severity: high", "#   severity: high\n#   severity_weight: -1"
            ),
            "must be positive",
            id="negative-weight",
        ),
        pytest.param(
            lambda body: body.replace(
                "#   severity: high", "#   severity: high\n#   severity_weight: heavy"
            ),
            "must be a number",
            id="non-numeric-weight",
        ),
        # The fix prompts send this text to the model. A rule shipped without it
        # leaves the model reinventing the remediation from the finding message
        # alone, which is how a bare `read_only: true` reached a database
        # service — so it fails the seed rather than merely warning in the docs.
        pytest.param(
            lambda body: body.replace(
                "#   examples:\n#     fix: |\n#       Do the thing the rule asks for.\n",
                "",
            ),
            "no 'custom.examples.fix'",
            id="no-remediation",
        ),
    ],
)
def test_rule_from_path_rejects_broken_metadata(
    tmp_path: Path, mutation: object, expected: str
) -> None:
    path = _write(tmp_path, mutation(_VALID_METADATA))  # type: ignore[operator]
    with pytest.raises(RuleMetadataError, match=re.escape(expected)):
        rule_from_path(path, tmp_path)


def test_rule_from_path_rejects_an_unknown_engine_directory(tmp_path: Path) -> None:
    path = _write(tmp_path, _VALID_METADATA, "ci_gitlab/security/example.rego")
    with pytest.raises(RuleMetadataError, match="unknown engine directory"):
        rule_from_path(path, tmp_path)


def test_rule_from_path_rejects_an_unknown_category_directory(tmp_path: Path) -> None:
    path = _write(tmp_path, _VALID_METADATA, "ci_workflow/cost/example.rego")
    with pytest.raises(RuleMetadataError, match="not an Category"):
        rule_from_path(path, tmp_path)


def test_rule_from_path_rejects_a_rule_outside_the_domain_category_layout(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, _VALID_METADATA, "ci_workflow/example.rego")
    with pytest.raises(RuleMetadataError, match="path segment"):
        rule_from_path(path, tmp_path)


# ─── discover_rules ──────────────────────────────────────────────────────────


def test_discover_rules_reports_every_problem_at_once(tmp_path: Path) -> None:
    _write(
        tmp_path,
        _VALID_METADATA.replace("# METADATA\n", ""),
        "ci_workflow/security/a.rego",
    )
    _write(
        tmp_path,
        _VALID_METADATA.replace("severity: high", "severity: nope"),
        "ci_workflow/security/b.rego",
    )
    with pytest.raises(RuleMetadataError) as exc:
        discover_rules(tmp_path)
    assert "2 rule file(s)" in str(exc.value)


def test_discover_rules_skips_test_files(tmp_path: Path) -> None:
    _write(tmp_path, _VALID_METADATA, "ci_workflow/security/example.rego")
    _write(tmp_path, "package whatever\n", "ci_workflow/security/example_test.rego")
    assert [r["slug"] for r in discover_rules(tmp_path)] == ["example"]


# ─── the real catalog ────────────────────────────────────────────────────────


def test_every_shipped_rule_is_catalogued() -> None:
    """No rule file is skipped, and no two rules collide within an engine."""
    rules = discover_rules()
    assert len(rules) == len(list(iter_rule_files()))
    keys = [(r["domain"], r["slug"]) for r in rules]
    assert len(set(keys)) == len(keys)


def test_shipped_rules_declare_a_known_detection_method() -> None:
    for path in iter_rule_files():
        block = extract_metadata_block(path.read_text(encoding="utf-8")) or ""
        match = re.search(r"^\s*detection:\s*(\S+)\s*$", block, re.M)
        assert match, f"{path.relative_to(RULES_DIR)}: no custom.detection"
        assert match.group(1) in VALID_DETECTION_METHODS


def test_package_declaration_matches_the_file_path() -> None:
    """The evaluator derives package names from paths; a mismatch is a dead rule."""
    for path in iter_rule_files():
        expected = "greensecops." + ".".join(
            path.relative_to(RULES_DIR).with_suffix("").parts
        )
        declared = re.search(
            r"^package\s+(\S+)", path.read_text(encoding="utf-8"), re.M
        )
        assert declared, f"{path.relative_to(RULES_DIR)}: no package declaration"
        assert declared.group(1) == expected


def test_metadata_severity_matches_the_severity_the_rule_emits() -> None:
    """The catalog's severity and the finding's severity must be the same value.

    They are written twice — once in METADATA for the docs and the Rule row,
    once as a literal in the violation object — so nothing but a test keeps
    them in step.
    """
    for path in iter_rule_files():
        declared = rule_from_path(path)["severity"]
        emitted = set(
            re.findall(r'"severity":\s*"(\w+)"', path.read_text(encoding="utf-8"))
        )
        assert emitted == {declared.value}, (
            f"{path.relative_to(RULES_DIR)}: METADATA says {declared.value}, "
            f"violation body emits {sorted(emitted)}"
        )


def test_metadata_category_matches_the_category_the_rule_emits() -> None:
    for path in iter_rule_files():
        category = path.parent.name
        emitted = set(
            re.findall(r'"category":\s*"(\w+)"', path.read_text(encoding="utf-8"))
        )
        assert emitted == {category}, (
            f"{path.relative_to(RULES_DIR)}: lives under {category}/ but emits {sorted(emitted)}"
        )


def test_rule_slug_matches_the_rule_field_it_emits() -> None:
    """A violation's `rule` key is the slug findings are keyed on."""
    for path in iter_rule_files():
        emitted = set(
            re.findall(r'"rule":\s*"(\w+)"', path.read_text(encoding="utf-8"))
        )
        assert emitted == {path.stem}, (
            f"{path.relative_to(RULES_DIR)}: emits rule={sorted(emitted)}, expected {path.stem}"
        )
