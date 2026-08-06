"""Sphinx extension: auto-generate rule pages from OPA METADATA annotations in .rego files."""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml
from sphinx.application import Sphinx
from sphinx.util import logging

# The backend package is not installed in the docs environment, but
# app.core.rego_metadata is deliberately stdlib-only so it can be imported
# from here by path. See that module for why the scanning is shared.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.core.rego_metadata import (
    iter_rule_files,
    read_metadata_block,
    severity_rank,
)

logger = logging.getLogger(__name__)

_VALID_SEVERITIES = {"critical", "high", "medium", "low", "info"}

_DETECTION_LABELS = {
    "static_analysis": "Checks field presence or value in the workflow YAML.",
    "pattern_matching": "Regex or keyword matching on string field values.",
    "heuristic": "Structural comparison across multiple jobs or steps.",
    "cloud_posture": "Checks a live AWS resource's described state.",
    "dynamic_analysis": "Checks measured runtime telemetry from a completed workflow run.",
}

_VALID_DETECTION_METHODS = set(_DETECTION_LABELS)

# Every rule file lives at app/rules/<domain>/<category>/<name>.rego — one
# analysis engine per domain. Human-friendly titles for the domain-level
# index pages; falls back to a title-cased slug for any domain added here
# without an entry.
_DOMAIN_LABELS = {
    "ci_workflow": "CI Workflow (static)",
    "ci_telemetry": "CI Telemetry (dynamic)",
    "iac_terraform": "Terraform (IaC)",
    "cloud_aws": "AWS Cloud Posture (dynamic)",
    "container_docker": "Docker & Compose (static)",
    "container_runtime": "Docker Runtime (dynamic)",
}

# Each engine's examples are written in the language it actually analyses, so
# highlighting them all as YAML was wrong for four of the six — and Pygments
# treats a failed lex as a warning, which ``-W`` turns into a failed build the
# moment an example contains JSON braces. Anything unlisted falls back to
# ``text``, which never fails to lex.
_EXAMPLE_LANGUAGES = {
    "ci_workflow": "yaml",
    "ci_telemetry": "yaml",
    "iac_terraform": "terraform",
    "cloud_aws": "bash",
    "container_docker": "docker",
    "container_runtime": "yaml",
}


def _example_language(domain: str, snippet: str) -> str:
    """Pick the lexer for one example.

    The Docker engine analyses two languages, so its examples are Dockerfiles
    or Compose YAML depending on which rule they illustrate — the only case
    where the engine alone does not settle it.
    """
    if domain == "container_docker" and re.match(r"^\s*services:", snippet):
        return "yaml"
    return _EXAMPLE_LANGUAGES.get(domain, "text")


def _rst_escape(text: str) -> str:
    """Escape characters reStructuredText treats as inline markup.

    Rule titles/descriptions are free text pulled from YAML METADATA blocks,
    not authored as RST — an unmatched ``*`` (e.g. a wildcard IAM action like
    ``"service:*"``) or stray backtick breaks the generated page's parsing.
    Only escapes what's actually free text; code-block content is untouched.
    """
    return text.replace("\\", "\\\\").replace("*", "\\*").replace("`", "\\`")


def _summarize(text: str, limit: int = 120) -> str:
    """Shorten a description for an index table without breaking RST.

    Cutting at a fixed offset can land inside a word, and a fragment that ends
    in an underscore is read by docutils as a reference — ``no_`` from a
    description mentioning ``no_cache_bust`` becomes an unresolved target and
    fails the ``-W`` build. Cutting on a word boundary (and dropping any
    trailing underscore anyway) keeps the summary plain text.
    """
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = head.rsplit(" ", 1)[0] if " " in head else head
    return cut.rstrip("_ ") + "..."


def _parse_metadata(filepath: Path) -> dict[str, Any] | None:
    """The rule's METADATA block, parsed.

    Scanning is shared with the backend seeder and the CI validators
    (``app.core.rego_metadata``), which returns the block's raw YAML text so
    each of the three environments can parse it with the loader it already
    has — this one has PyYAML.
    """
    block = read_metadata_block(filepath)
    if block is None:
        return None
    return yaml.safe_load(block) or {}


def _rule_info(filepath: Path, rules_base: Path) -> dict[str, Any] | None:
    meta = _parse_metadata(filepath)
    if not meta:
        return None

    # <domain>/<category>/<name>.rego for every rule in every engine.
    rel = filepath.relative_to(rules_base)
    domain, category = rel.parts[0], rel.parts[1]
    rule_id = filepath.stem
    custom = meta.get("custom") or {}

    return {
        "title": _rst_escape(meta.get("title", rule_id)),
        "description": _rst_escape(meta.get("description", "")),
        "severity": custom.get("severity", "unknown"),
        "domain": domain,
        "category": category,
        "rule_id": rule_id,
        "related_resources": meta.get("related_resources") or [],
        "detection": custom.get("detection", ""),
        "examples": custom.get("examples") or {},
    }


def _render_rule_page(rule: dict[str, Any]) -> str:
    title = rule["title"]
    underline = "=" * len(title)

    detection_section = ""
    if rule["detection"]:
        label = _DETECTION_LABELS.get(rule["detection"], rule["detection"])
        detection_section = (
            f"\nDetection\n---------\n\n``{rule['detection']}`` — {label}\n"
        )

    examples_section = ""
    examples = rule["examples"]
    if examples:
        parts: list[str] = ["\nExamples\n--------\n"]
        bad = (examples.get("bad") or "").rstrip()
        good = (examples.get("good") or "").rstrip()
        fix = _rst_escape((examples.get("fix") or "").strip())
        if bad:
            indented = "\n".join("   " + ln for ln in bad.splitlines())
            parts.append(
                "**Non-compliant:**\n\n.. code-block:: "
                f"{_example_language(rule['domain'], bad)}\n\n{indented}\n"
            )
        if good:
            indented = "\n".join("   " + ln for ln in good.splitlines())
            parts.append(
                "**Compliant:**\n\n.. code-block:: "
                f"{_example_language(rule['domain'], good)}\n\n{indented}\n"
            )
        if fix:
            parts.append(f"**Fix**: {fix}\n")
        examples_section = "\n".join(parts)

    resources_section = ""
    if rule["related_resources"]:
        refs = "\n".join(
            f"- {r['ref'] if isinstance(r, dict) else r}"
            for r in rule["related_resources"]
        )
        resources_section = f"\nSee also\n--------\n\n{refs}\n"

    domain_label = _DOMAIN_LABELS.get(
        rule["domain"], rule["domain"].replace("_", " ").title()
    )

    return f"""{title}
{underline}

.. list-table::
   :stub-columns: 1
   :widths: 20 80

   * - Rule ID
     - ``{rule["rule_id"]}``
   * - Engine
     - {domain_label}
   * - Category
     - {rule["category"]}
   * - Severity
     - {rule["severity"]}

{rule["description"]}
{detection_section}{examples_section}{resources_section}"""


def _render_category_index(category: str, rules: list[dict[str, Any]]) -> str:
    title = f"{category.capitalize()} Rules"
    underline = "=" * len(title)

    toctree_entries = "\n".join(
        f"   {r['rule_id']}" for r in sorted(rules, key=lambda r: r["rule_id"])
    )

    table_rows = "\n".join(
        f"   * - :doc:`{r['rule_id']}`\n"
        f"     - {r['severity']}\n"
        f"     - {_summarize(r['description'])}"
        for r in sorted(
            rules,
            key=lambda r: (severity_rank(r["severity"]), r["rule_id"]),
        )
    )

    return f"""{title}
{underline}

.. toctree::
   :maxdepth: 1
   :hidden:

{toctree_entries}

.. list-table::
   :header-rows: 1
   :widths: 30 15 55

   * - Rule
     - Severity
     - Description
{table_rows}
"""


def _render_domain_index(
    domain: str, categories: dict[str, list[dict[str, Any]]]
) -> str:
    title = _DOMAIN_LABELS.get(domain, domain.replace("_", " ").title())
    underline = "=" * len(title)

    toctree_entries = "\n".join(f"   {cat}/index" for cat in sorted(categories))
    category_summaries = "\n\n".join(
        f"**{cat.capitalize()}** — {len(rules)} rule{'s' if len(rules) != 1 else ''}"
        for cat, rules in sorted(categories.items())
    )

    return f"""{title}
{underline}

{category_summaries}

.. toctree::
   :maxdepth: 2

{toctree_entries}
"""


def _render_rules_index(domains: dict[str, dict[str, list[dict[str, Any]]]]) -> str:
    toctree_entries = "\n".join(f"   {domain}/index" for domain in sorted(domains))

    domain_summaries = "\n\n".join(
        f"**{_DOMAIN_LABELS.get(domain, domain.replace('_', ' ').title())}** — "
        f"{sum(len(rules) for rules in categories.values())} rule"
        f"{'s' if sum(len(rules) for rules in categories.values()) != 1 else ''} "
        f"across {len(categories)} categor{'y' if len(categories) == 1 else 'ies'}"
        for domain, categories in sorted(domains.items())
    )

    return f"""Rules Reference
===============

Four analysis engines share this rule catalog: static CI-workflow YAML
analysis, dynamic CI-telemetry analysis, static Terraform (IaC) analysis, and
live AWS cloud-posture scanning. Each rule is a Rego policy evaluated by the
same OPA-backed engine.

{domain_summaries}

.. toctree::
   :maxdepth: 3

{toctree_entries}
"""


def _warn_rule(rule: dict[str, Any], filepath: Path, app: Sphinx) -> None:
    label = str(filepath)
    if not rule["description"]:
        logger.warning(f"rego_autodoc: {label}: missing 'description'")
    if rule["severity"] == "unknown":
        logger.warning(f"rego_autodoc: {label}: missing 'custom.severity'")
    elif rule["severity"] not in _VALID_SEVERITIES:
        logger.warning(
            f"rego_autodoc: {label}: invalid severity '{rule['severity']}'"
            f" (must be one of: {', '.join(sorted(_VALID_SEVERITIES))})"
        )
    if not rule["detection"]:
        logger.warning(f"rego_autodoc: {label}: missing 'custom.detection'")
    elif rule["detection"] not in _VALID_DETECTION_METHODS:
        logger.warning(
            f"rego_autodoc: {label}: invalid detection '{rule['detection']}'"
            f" (must be one of: {', '.join(sorted(_VALID_DETECTION_METHODS))})"
        )
    examples = rule["examples"]
    for field in ("bad", "good", "fix"):
        if not (examples.get(field) or "").strip():
            logger.warning(f"rego_autodoc: {label}: missing 'custom.examples.{field}'")


def generate_rule_pages(app: Sphinx) -> None:
    rules_base = Path(app.srcdir).parent / "backend" / "app" / "rules"
    rules_out = Path(app.srcdir) / "rules"

    if not rules_base.exists():
        logger.warning(f"rego_autodoc: rules directory not found: {rules_base}")
        return

    # Fully generated output — wipe before regenerating so a renamed or
    # removed rule doesn't leave an orphaned page behind (an orphan isn't
    # linked from any toctree, which -W turns into a hard build failure).
    if rules_out.exists():
        shutil.rmtree(rules_out)
    rules_out.mkdir(exist_ok=True)
    domains: dict[str, dict[str, list[dict[str, Any]]]] = {}

    for rego_file in iter_rule_files(rules_base):
        info = _rule_info(rego_file, rules_base)
        if info is None:
            logger.warning(
                f"rego_autodoc: no METADATA in {rego_file.relative_to(rules_base)}, skipping"
            )
            continue
        _warn_rule(info, rego_file.relative_to(rules_base), app)
        categories = domains.setdefault(info["domain"], {})
        categories.setdefault(info["category"], []).append(info)

        cat_dir = rules_out / info["domain"] / info["category"]
        cat_dir.mkdir(parents=True, exist_ok=True)
        (cat_dir / f"{info['rule_id']}.rst").write_text(
            _render_rule_page(info), encoding="utf-8"
        )

    for domain, categories in domains.items():
        domain_dir = rules_out / domain
        for cat, rules in categories.items():
            (domain_dir / cat / "index.rst").write_text(
                _render_category_index(cat, rules), encoding="utf-8"
            )
        (domain_dir / "index.rst").write_text(
            _render_domain_index(domain, categories), encoding="utf-8"
        )

    (rules_out / "index.rst").write_text(_render_rules_index(domains), encoding="utf-8")


def generate_reference_page(app: Sphinx) -> None:
    """Generate the reference-workflow page from examples/deploy.yml.

    The example file is the single source of truth for the compliant workflow
    shown on the landing page; embedding it here (rather than a hand-copied
    snippet) keeps the docs in lock-step, and CI validates that it produces zero
    violations against every rule.
    """
    example = Path(app.srcdir).parent / "examples" / "deploy.yml"
    out_path = Path(app.srcdir) / "reference.rst"

    if not example.exists():
        logger.warning(f"rego_autodoc: reference example not found: {example}")
        return

    indented = "\n".join(
        f"   {line}" if line.strip() else ""
        for line in example.read_text(encoding="utf-8").splitlines()
    )
    title = "Reference workflow"
    page = (
        f"{title}\n{'=' * len(title)}\n\n"
        "A complete GitHub Actions workflow that passes every GreenSecOps rule "
        "across all five categories. It is validated in CI "
        "(``scripts/validate_examples.py``) to produce zero violations, so it "
        "stays state of the art as new rules are added. This is the same file "
        "shown on the landing page — the single source of truth lives at "
        "``examples/deploy.yml``.\n\n"
        ".. code-block:: yaml\n\n"
        f"{indented}\n"
    )
    out_path.write_text(page, encoding="utf-8")


def setup(app: Sphinx) -> dict[str, Any]:
    app.connect("builder-inited", generate_rule_pages)
    app.connect("builder-inited", generate_reference_page)
    return {"version": "0.1", "parallel_read_safe": True}
