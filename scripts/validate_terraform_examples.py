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
``__tf_file`` tagging and per-block-type list-concatenation feed OPA.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[1]
RULES_DIR = ROOT / "backend" / "app" / "rules"
EXAMPLES_DIR = ROOT / "examples" / "terraform"
OPA_BIN = os.environ.get("OPA_BIN", "opa")

# Evaluate ONLY the iac_terraform packages, exactly like production's
# app.services.opa.evaluator.evaluate_terraform. The cross-domain aggregate is
# deliberately not used here: some ci_workflow rules fire on a negation (e.g.
# `not input.name`), which is vacuously true for a Terraform document and would
# be a cross-domain false positive. This comprehension collects every violation
# under greensecops.iac_terraform.<category>.<rule> and nothing else.
_TERRAFORM_VIOLATIONS_QUERY = (
    "[v | v := data.greensecops.iac_terraform[_][_].violations[_]]"
)

# Reuse the exact parse+merge production feeds to OPA rather than re-implementing
# HCL handling here.
sys.path.insert(0, str(ROOT / "backend"))
from app.services.terraform.hcl_parser import (  # noqa: E402
    merge_terraform_configs,
)


def _opa_eval_slugs(merged_config: dict) -> list[str]:
    """Return the sorted rule slugs ``merged_config`` trips across the suite."""
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as handle:
        json.dump(merged_config, handle)
        input_path = handle.name
    cmd = [
        OPA_BIN,
        "eval",
        "-d",
        str(RULES_DIR),
        "-f",
        "raw",
        "-i",
        input_path,
        _TERRAFORM_VIOLATIONS_QUERY,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    finally:
        os.unlink(input_path)
    if proc.returncode != 0:
        raise RuntimeError(f"opa eval failed:\n{proc.stderr.strip()}")
    violations = json.loads(proc.stdout or "[]")
    return sorted({v["rule"] for v in violations})


def _read_tf_files(case_dir: Path) -> list[tuple[str, str]]:
    """Collect every ``.tf`` / ``.tf.json`` file in a case as (name, content)."""
    files = sorted(
        p
        for p in case_dir.iterdir()
        if p.suffix == ".tf" or p.name.endswith(".tf.json")
    )
    return [(p.name, p.read_text(encoding="utf-8")) for p in files]


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
        tf_files = _read_tf_files(case_dir)
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
