#!/usr/bin/env python3
"""Regenerate the backend Terraform test fixtures' ``expected.json`` files.

``backend/tests/fixtures/terraform/`` holds real Terraform vendored verbatim
from public repos, so the violations each case trips are a fact about the rule
suite rather than something worth hand-authoring. This runs the same
parse → merge → OPA pipeline the example validators use
(``scripts/opa_terraform_eval.py``, which itself reuses production's
``merge_terraform_configs``) and records the result.

pytest never runs this: the backend test environment has no ``opa`` binary, so
``_evaluate`` stays mocked there and ``expected.json`` is the recorded ground
truth those tests replay. Re-run after vendoring a new case or changing a rule:

    python scripts/regenerate_terraform_fixtures.py

``opa`` must be on ``PATH``, or set ``OPA_BIN`` to its location.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opa_terraform_eval import (
    ROOT,
    evaluate_violations,
    merge_terraform_configs,
)

FIXTURES = ROOT / "backend" / "tests" / "fixtures" / "terraform"

# Provenance recorded in each expected.json, so a reader can trace a fixture
# back to the commit it was vendored from without leaving the file.
SOURCES: dict[str, dict[str, str]] = {
    "terragoat_aws": {
        "repository": "https://github.com/bridgecrewio/terragoat",
        "path": "terraform/aws",
        "ref": "729f8da62c6a85ce4af5ad3d123de97776d954c4",
        "license": "Apache-2.0",
    },
    "terraform_aws_security_group": {
        "repository": "https://github.com/terraform-aws-modules/terraform-aws-security-group",
        "path": ".",
        "ref": "58d8e895915f5573767081142d063b7caf7a2b47",
        "license": "Apache-2.0",
    },
    "terraform_aws_vpc_complete": {
        "repository": "https://github.com/terraform-aws-modules/terraform-aws-vpc",
        "path": "examples/complete",
        "ref": "3ffbd46fb1c7733e1b34d8666893280454e27436",
        "license": "Apache-2.0",
    },
}


def _tf_files(case_dir: Path) -> list[tuple[str, str]]:
    paths = sorted(
        p for p in case_dir.iterdir() if p.name.endswith((".tf", ".tf.json"))
    )
    return [(p.name, p.read_text(encoding="utf-8")) for p in paths]


def _violation_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Reshape an OPA violation into ``TerraformOpaViolation`` keyword arguments."""
    return {
        "rule_slug": raw["rule"],
        "severity": raw["severity"],
        "category": raw["category"],
        "message": raw["message"],
        "resource_address": raw["resource_address"],
        "file_path": raw["file_path"],
        "line_start": raw["line_start"],
        "line_end": raw["line_end"],
    }


def main() -> int:
    for case_dir in sorted(p for p in FIXTURES.iterdir() if p.is_dir()):
        files = _tf_files(case_dir)
        if not files:
            continue
        raw_violations = evaluate_violations(merge_terraform_configs(files))
        violations = sorted(
            (_violation_payload(v) for v in raw_violations),
            key=lambda v: (v["rule_slug"], v["resource_address"], v["message"]),
        )
        # One TerraformFinding per (rule, resource_address): the fingerprint
        # (app/services/deduplication.py) keys on exactly that pair, so a rule
        # that fires twice on one resource — terragoat's security group, open on
        # both 22 and 80 — collapses to a single finding.
        fingerprints = {(v["rule_slug"], v["resource_address"]) for v in violations}
        payload = {
            "source": SOURCES[case_dir.name],
            "files": [name for name, _ in files],
            "violations": violations,
            "expected_finding_count": len(fingerprints),
            "expected_grade": "A+++" if not fingerprints else None,
        }
        out = case_dir / "expected.json"
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"{case_dir.name}: {len(violations)} violations → {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
