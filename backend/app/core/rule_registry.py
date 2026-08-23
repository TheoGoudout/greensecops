"""Derive the ``Rule`` catalog from the Rego policy files themselves.

Replaces the six hand-maintained ``*_INITIAL_RULES`` lists that used to live in
``app/core/db.py``. Those lists were a second copy of what every ``.rego`` file
already declares in its ``# METADATA`` block, and the copy had rotted: one rule
was never seeded at all, eight carried a severity the docs contradicted, and 37
descriptions had drifted from the published text.

A rule file is therefore the single source of truth. Its path supplies identity
(``app/rules/<domain>/<category>/<slug>.rego``) and its METADATA block supplies
everything the catalog shows. Adding a rule is adding two files — the policy and
its test — with no registration step to forget.

Validation is strict and raises: a rule whose METADATA is missing or malformed
aborts the seed rather than being skipped. The whole reason this module exists
is that the previous failure mode was silence — a rule that no one had
registered simply never produced findings, and nothing said so.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.core.rego_metadata import RULES_DIR, iter_rule_files, read_metadata_block
from app.models import IssueCategory, IssueSeverity, RuleDomain

# What `severity_weight` a rule gets when its METADATA does not name one. These
# are the modal weights of the old hand-maintained lists, so the default is
# what most rules of that severity already scored at. A rule that genuinely
# deserves more or less weight within its band overrides it with
# `custom.severity_weight`; twelve rules do.
_DEFAULT_SEVERITY_WEIGHTS: dict[IssueSeverity, float] = {
    IssueSeverity.critical: 3.5,
    IssueSeverity.high: 1.8,
    IssueSeverity.medium: 1.0,
    IssueSeverity.low: 0.5,
    IssueSeverity.info: 0.2,
}

# Mirrors docs/ext/rego_autodoc.py's _DETECTION_LABELS. Validated here so a typo
# fails the seed rather than silently rendering a raw slug into the docs.
VALID_DETECTION_METHODS = frozenset(
    {
        "static_analysis",
        "pattern_matching",
        "heuristic",
        "cloud_posture",
        "dynamic_analysis",
    }
)

# Rule.title / Rule.description column limits (app/models/db/rule.py).
_MAX_TITLE = 255
_MAX_DESCRIPTION = 2048


class RuleMetadataError(ValueError):
    """A rule file's METADATA is missing, malformed, or incomplete."""


def _fail(path: Path, problem: str) -> RuleMetadataError:
    try:
        label: Path | str = path.relative_to(RULES_DIR)
    except ValueError:
        label = path
    return RuleMetadataError(f"{label}: {problem}")


def _parse_metadata(path: Path) -> dict[str, Any]:
    raw = read_metadata_block(path)
    if raw is None:
        raise _fail(path, "no '# METADATA' block")
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise _fail(path, f"METADATA is not valid YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        raise _fail(path, "METADATA block is not a mapping")
    return parsed


def rule_from_path(path: Path, rules_dir: Path | None = None) -> dict[str, Any]:
    """Build one ``Rule`` field dict from a policy file.

    Raises ``RuleMetadataError`` if the file cannot be catalogued.
    """
    base = RULES_DIR if rules_dir is None else rules_dir
    parts = path.relative_to(base).parts
    if len(parts) != 3:
        raise _fail(
            path,
            "expected app/rules/<domain>/<category>/<slug>.rego, "
            f"got {len(parts)} path segment(s)",
        )
    domain_dir, category_dir, _ = parts

    # RuleDomain's members *are* the directory names, so no lookup table stands
    # between the two to be kept in step.
    try:
        domain = RuleDomain(domain_dir)
    except ValueError as exc:
        raise _fail(
            path,
            f"unknown engine directory '{domain_dir}' — add it to RuleDomain",
        ) from exc
    try:
        category = IssueCategory(category_dir)
    except ValueError as exc:
        raise _fail(path, f"'{category_dir}' is not an IssueCategory") from exc

    meta = _parse_metadata(path)
    custom = meta.get("custom") or {}
    if not isinstance(custom, dict):
        raise _fail(path, "'custom' is not a mapping")

    title = str(meta.get("title") or "").strip()
    if not title:
        raise _fail(path, "METADATA has no 'title'")
    if len(title) > _MAX_TITLE:
        raise _fail(path, f"title is {len(title)} chars (max {_MAX_TITLE})")

    description = str(meta.get("description") or "").strip()
    if not description:
        raise _fail(path, "METADATA has no 'description'")
    if len(description) > _MAX_DESCRIPTION:
        raise _fail(
            path, f"description is {len(description)} chars (max {_MAX_DESCRIPTION})"
        )

    raw_severity = custom.get("severity")
    if raw_severity is None:
        raise _fail(path, "METADATA has no 'custom.severity'")
    try:
        severity = IssueSeverity(str(raw_severity))
    except ValueError as exc:
        raise _fail(path, f"'{raw_severity}' is not an IssueSeverity") from exc

    detection = custom.get("detection")
    if detection not in VALID_DETECTION_METHODS:
        raise _fail(
            path,
            f"'custom.detection' is {detection!r}, must be one of "
            f"{', '.join(sorted(VALID_DETECTION_METHODS))}",
        )

    weight = custom.get("severity_weight", _DEFAULT_SEVERITY_WEIGHTS[severity])
    if not isinstance(weight, int | float) or isinstance(weight, bool):
        raise _fail(path, f"'custom.severity_weight' is {weight!r}, must be a number")
    if weight <= 0:
        raise _fail(path, f"'custom.severity_weight' is {weight}, must be positive")

    return {
        "slug": path.stem,
        "domain": domain,
        "category": category,
        "severity": severity,
        "severity_weight": float(weight),
        "title": title,
        "description": description,
    }


def discover_rules(rules_dir: Path | None = None) -> list[dict[str, Any]]:
    """Every shipped rule, as ``Rule`` field dicts, in stable path order.

    Collects *all* METADATA problems before raising, so a contributor adding
    several rules sees every one of them in a single run rather than fixing
    them one boot at a time.
    """
    base = RULES_DIR if rules_dir is None else rules_dir
    rules: list[dict[str, Any]] = []
    problems: list[str] = []
    seen: dict[tuple[RuleDomain, str], Path] = {}

    for path in iter_rule_files(base):
        try:
            rule = rule_from_path(path, base)
        except RuleMetadataError as exc:
            problems.append(str(exc))
            continue

        # Slugs collide across engines on purpose — `rds_not_encrypted` is a
        # real finding both in Terraform source and in a live account — so the
        # identity is (domain, slug). A collision *within* one engine is a bug.
        key = (rule["domain"], rule["slug"])
        if key in seen:
            problems.append(
                f"{path.relative_to(base)}: duplicate rule "
                f"{rule['domain'].value}/{rule['slug']} "
                f"(already defined by {seen[key].relative_to(base)})"
            )
            continue
        seen[key] = path
        rules.append(rule)

    if problems:
        raise RuleMetadataError(
            f"{len(problems)} rule file(s) could not be catalogued:\n  "
            + "\n  ".join(problems)
        )
    return rules
