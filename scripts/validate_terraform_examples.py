#!/usr/bin/env python3
"""Validate the shipped Terraform examples against the full OPA rule suite.

Run in CI (``.github/workflows/opa.yml``) and locally. This is the Terraform
counterpart to ``scripts/validate_examples.py``: every example module under
``examples/terraform/<case>/`` is parsed and merged exactly as production does
(``app.services.terraform.hcl_parser.merge_terraform_configs``), evaluated
against the full ``iac_terraform`` rule suite, and its tripped rule slugs are
asserted to match the case's ``expected.yaml`` **exactly**. An exact match catches both
a rule that stopped firing on a module it should catch (a regression) and a
rule that started firing on a module it shouldn't (a false positive) as the
ruleset evolves.

Adding a new case is intentionally a no-code operation: drop a folder under
``examples/terraform/`` containing one or more ``.tf`` / ``.tf.json`` files plus
an ``expected.yaml``, and it is picked up automatically. See
``examples/terraform/README.md``.

Merging reuses the production code path, so an example that passes here is
faithful to what a real scan of the same files would see — the same
``__tf_file`` tagging and per-block-type list-concatenation feed OPA. The
parse/merge/eval pipeline itself lives in ``scripts/opa_terraform_eval.py``,
shared with ``scripts/validate_deploy_terraform.py`` so the two checks can't
drift apart.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from opa_terraform_eval import (
    ROOT,
    collect_tf_files,
    evaluate_violations,
    merge_terraform_configs,
)
from ruamel.yaml import YAML

EXAMPLES_DIR = ROOT / "examples" / "terraform"


def _opa_eval_slugs(merged_config: dict[str, Any]) -> list[str]:
    """Return the sorted rule slugs ``merged_config`` trips across the suite."""
    return sorted({v["rule"] for v in evaluate_violations(merged_config)})


def _load_expected(case_dir: Path) -> list[str]:
    expected_file = case_dir / "expected.yaml"
    if not expected_file.exists():
        raise FileNotFoundError(
            f"{case_dir.name}: missing expected.yaml "
            "(see examples/terraform/README.md)"
        )
    data = YAML(typ="safe").load(expected_file.read_text(encoding="utf-8")) or {}
    return sorted(data.get("violations") or [])


def _describe_mismatch(case_name: str, expected: list[str], tripped: list[str]) -> str:
    missing = sorted(set(expected) - set(tripped))
    unexpected = sorted(set(tripped) - set(expected))
    parts = []
    if missing:
        parts.append(f"expected but did not fire: {missing}")
    if unexpected:
        parts.append(f"fired but not expected: {unexpected}")
    return f"{case_name}: " + "; ".join(parts)


def main() -> int:
    if not EXAMPLES_DIR.is_dir():
        print(f"No Terraform examples directory at {EXAMPLES_DIR}", file=sys.stderr)
        return 1

    errors: list[str] = []
    checked = 0
    for case_dir in sorted(p for p in EXAMPLES_DIR.iterdir() if p.is_dir()):
        tf_files = collect_tf_files(case_dir)
        if not tf_files:
            errors.append(f"{case_dir.name}: no .tf/.tf.json files found")
            continue
        try:
            expected = _load_expected(case_dir)
        except FileNotFoundError as exc:
            errors.append(str(exc))
            continue
        tripped = _opa_eval_slugs(merge_terraform_configs(tf_files))
        checked += 1
        if tripped != expected:
            errors.append(_describe_mismatch(case_dir.name, expected, tripped))

    if errors:
        print("Terraform example validation FAILED:\n", file=sys.stderr)
        for err in errors:
            print(f"  ✗ {err}", file=sys.stderr)
        print(f"\n{len(errors)} problem(s) found.", file=sys.stderr)
        return 1
    print(
        f"All {checked} Terraform example(s) validated against the OPA rule suite ✅"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
