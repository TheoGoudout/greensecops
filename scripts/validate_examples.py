#!/usr/bin/env python3
"""Validate the shipped workflow examples against the full OPA rule suite.

Run in CI (``.github/workflows/opa.yml``) and locally. Two independent checks:

1. **Canonical examples** (``examples/``) — the single source of truth rendered
   into the landing page and docs:
     * ``deploy.yml`` must produce **zero** violations across every rule, so the
       "reference-quality" workflow can never silently drift as new rules land.
     * ``deploy-insecure.yml`` (the "before" workflow) must still trip the
       advertised violations, keeping the before/after story truthful.

2. **Per-rule METADATA examples** (both directions) — for every rule, its
   ``good`` example must NOT violate its own rule and its ``bad`` example MUST
   trigger it. This catches inverted/broken rules (e.g. a "compliant" snippet
   that fails the very rule it illustrates) as the ruleset evolves.

Workflow YAML is parsed with ruamel.yaml (YAML 1.2 core schema), mirroring
``app.services.opa.evaluator.parse_workflow_yaml`` so that the bare ``on:`` key
stays the string "on" (PyYAML's YAML 1.1 ``safe_load`` coerces it to boolean
True, which silently disables every ``input.on`` rule).
"""

from __future__ import annotations

import sys
from pathlib import Path

from opa_eval import ROOT, RULES_DIR, run_opa_eval, slugs
from ruamel.yaml import YAML

# Per-rule METADATA `good`/`bad` examples are only self-testable for the
# ci_workflow domain, whose examples are literal GitHub Actions workflow YAML
# that maps directly onto the OPA input schema. iac_terraform examples are
# illustrative Terraform HCL and cloud_aws examples are illustrative CLI
# output — neither parses as executable OPA input, so they are excluded here.
CI_WORKFLOW_RULES_DIR = RULES_DIR / "ci_workflow"
EXAMPLES_DIR = ROOT / "examples"

# deploy-insecure.yml must keep tripping at least these (the landing page's
# "1 critical, 2 high-severity issues" caption).
INSECURE_EXPECTED = {"hardcoded_secrets", "unpinned_actions", "caching_missing"}


# Reuse the production parser rather than a local copy of it. The two had
# already diverged once in spirit — a rule reading the `__start_line__` keys
# the real parser stamps would have had its METADATA `bad` example silently
# fail to fire here, passing CI while being broken in production.
sys.path.insert(0, str(ROOT / "backend"))
from app.core.rego_metadata import read_metadata_block  # noqa: E402
from app.services.workflow_parser import (
    parse_workflow_yaml as _parse_yaml,  # noqa: E402
)


def _parse_metadata(rego_path: Path) -> dict:
    """The rule's METADATA block, parsed with the loader this env has.

    Scanning is shared with the backend seeder and the docs extension
    (``app.core.rego_metadata``); see that module for why only the raw YAML
    text is shared and not the parse.
    """
    block = read_metadata_block(rego_path)
    if block is None:
        return {}
    return YAML(typ="safe").load(block) or {}


def check_canonical_examples() -> list[str]:
    errors: list[str] = []

    reference = EXAMPLES_DIR / "deploy.yml"
    violations = run_opa_eval(
        _parse_yaml(reference.read_text(encoding="utf-8")),
        "data.aggregate.all_violations",
        with_aggregate=True,
    )
    if violations:
        errors.append(
            f"{reference.name}: reference workflow must be violation-free, "
            f"but tripped {slugs(violations)}"
        )

    insecure = EXAMPLES_DIR / "deploy-insecure.yml"
    tripped = set(
        slugs(
            run_opa_eval(
                _parse_yaml(insecure.read_text(encoding="utf-8")),
                "data.aggregate.all_violations",
                with_aggregate=True,
            )
        )
    )
    missing = INSECURE_EXPECTED - tripped
    if missing:
        errors.append(
            f"{insecure.name}: expected to still trip {sorted(INSECURE_EXPECTED)}, "
            f"but {sorted(missing)} did not fire"
        )
    return errors


def check_rule_metadata_examples() -> list[str]:
    errors: list[str] = []
    for rego in sorted(CI_WORKFLOW_RULES_DIR.glob("*/*.rego")):
        if rego.name.endswith("_test.rego"):
            continue
        category, name = rego.parent.name, rego.stem
        examples = (_parse_metadata(rego).get("custom") or {}).get("examples") or {}
        query = f"data.greensecops.ci_workflow.{category}.{name}.violations"

        good = examples.get("good")
        if good:
            self_hits = run_opa_eval(_parse_yaml(good), query)
            if self_hits:
                errors.append(
                    f"{category}/{name}: 'good' example violates its own rule "
                    f"({len(self_hits)} violation(s)) — a compliant example must pass."
                )

        bad = examples.get("bad")
        if bad:
            self_hits = run_opa_eval(_parse_yaml(bad), query)
            if not self_hits:
                errors.append(
                    f"{category}/{name}: 'bad' example does not trigger its own rule "
                    "— a non-compliant example must demonstrate the violation."
                )
    return errors


def main() -> int:
    errors = check_canonical_examples() + check_rule_metadata_examples()
    if errors:
        print("Example validation FAILED:\n", file=sys.stderr)
        for err in errors:
            print(f"  ✗ {err}", file=sys.stderr)
        print(f"\n{len(errors)} problem(s) found.", file=sys.stderr)
        return 1
    print("All workflow examples validated against the OPA rule suite ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
