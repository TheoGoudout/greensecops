"""Sphinx extension: auto-generate rule pages from OPA METADATA annotations in .rego files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sphinx.application import Sphinx

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "unknown": 4}

_VALID_SEVERITIES = {"critical", "high", "medium", "low"}

_DETECTION_LABELS = {
    "static_analysis": "Checks field presence or value in the workflow YAML.",
    "pattern_matching": "Regex or keyword matching on string field values.",
    "heuristic": "Structural comparison across multiple jobs or steps.",
}

_VALID_DETECTION_METHODS = set(_DETECTION_LABELS)


def _parse_metadata(filepath: Path) -> dict[str, Any] | None:
    content = filepath.read_text(encoding="utf-8")
    lines = content.splitlines()

    metadata_lines: list[str] = []
    in_block = False

    for line in lines:
        if line.rstrip() == "# METADATA":
            in_block = True
            continue
        if in_block:
            if line.startswith("# "):
                metadata_lines.append(line[2:])
            elif line.rstrip() == "#":
                metadata_lines.append("")
            else:
                break

    if not metadata_lines:
        return None

    return yaml.safe_load("\n".join(metadata_lines)) or {}


def _rule_info(filepath: Path, rules_base: Path) -> dict[str, Any] | None:
    meta = _parse_metadata(filepath)
    if not meta:
        return None

    rel = filepath.relative_to(rules_base)
    category = rel.parts[0]
    rule_id = filepath.stem
    custom = meta.get("custom") or {}

    return {
        "title": meta.get("title", rule_id),
        "description": meta.get("description", ""),
        "severity": custom.get("severity", "unknown"),
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
        fix = (examples.get("fix") or "").strip()
        if bad:
            indented = "\n".join("   " + ln for ln in bad.splitlines())
            parts.append(f"**Non-compliant:**\n\n.. code-block:: yaml\n\n{indented}\n")
        if good:
            indented = "\n".join("   " + ln for ln in good.splitlines())
            parts.append(f"**Compliant:**\n\n.. code-block:: yaml\n\n{indented}\n")
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

    return f"""{title}
{underline}

.. list-table::
   :stub-columns: 1
   :widths: 20 80

   * - Rule ID
     - ``{rule["rule_id"]}``
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
        f"     - {r['description'][:120]}{'...' if len(r['description']) > 120 else ''}"
        for r in sorted(
            rules,
            key=lambda r: (_SEVERITY_ORDER.get(r["severity"], 4), r["rule_id"]),
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


def _render_rules_index(categories: dict[str, list[dict[str, Any]]]) -> str:
    toctree_entries = "\n".join(f"   {cat}/index" for cat in sorted(categories))

    category_summaries = "\n\n".join(
        f"**{cat.capitalize()}** — {len(rules)} rule{'s' if len(rules) != 1 else ''}"
        for cat, rules in sorted(categories.items())
    )

    return f"""Rules Reference
===============

{category_summaries}

.. toctree::
   :maxdepth: 2

{toctree_entries}
"""


def _warn_rule(rule: dict[str, Any], filepath: Path, app: Sphinx) -> None:
    label = str(filepath)
    if not rule["description"]:
        app.warn(f"rego_autodoc: {label}: missing 'description'")
    if rule["severity"] == "unknown":
        app.warn(f"rego_autodoc: {label}: missing 'custom.severity'")
    elif rule["severity"] not in _VALID_SEVERITIES:
        app.warn(
            f"rego_autodoc: {label}: invalid severity '{rule['severity']}'"
            f" (must be one of: {', '.join(sorted(_VALID_SEVERITIES))})"
        )
    if not rule["detection"]:
        app.warn(f"rego_autodoc: {label}: missing 'custom.detection'")
    elif rule["detection"] not in _VALID_DETECTION_METHODS:
        app.warn(
            f"rego_autodoc: {label}: invalid detection '{rule['detection']}'"
            f" (must be one of: {', '.join(sorted(_VALID_DETECTION_METHODS))})"
        )
    examples = rule["examples"]
    for field in ("bad", "good", "fix"):
        if not (examples.get(field) or "").strip():
            app.warn(f"rego_autodoc: {label}: missing 'custom.examples.{field}'")


def generate_rule_pages(app: Sphinx) -> None:
    rules_base = Path(app.srcdir).parent / "backend" / "app" / "rules"
    rules_out = Path(app.srcdir) / "rules"

    if not rules_base.exists():
        app.warn(f"rego_autodoc: rules directory not found: {rules_base}")
        return

    rules_out.mkdir(exist_ok=True)
    categories: dict[str, list[dict[str, Any]]] = {}

    for rego_file in sorted(rules_base.glob("**/*.rego")):
        if rego_file.name.endswith("_test.rego"):
            continue
        info = _rule_info(rego_file, rules_base)
        if info is None:
            app.warn(
                f"rego_autodoc: no METADATA in {rego_file.relative_to(rules_base)}, skipping"
            )
            continue
        _warn_rule(info, rego_file.relative_to(rules_base), app)
        categories.setdefault(info["category"], []).append(info)

        cat_dir = rules_out / info["category"]
        cat_dir.mkdir(exist_ok=True)
        (cat_dir / f"{info['rule_id']}.rst").write_text(
            _render_rule_page(info), encoding="utf-8"
        )

    for cat, rules in categories.items():
        cat_dir = rules_out / cat
        (cat_dir / "index.rst").write_text(
            _render_category_index(cat, rules), encoding="utf-8"
        )

    (rules_out / "index.rst").write_text(
        _render_rules_index(categories), encoding="utf-8"
    )


def setup(app: Sphinx) -> dict[str, Any]:
    app.connect("builder-inited", generate_rule_pages)
    return {"version": "0.1", "parallel_read_safe": True}
