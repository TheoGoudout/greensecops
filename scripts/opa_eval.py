"""Running ``opa eval``, once, for every checker in this repo.

Five scripts feed a JSON document to OPA and read violations back:
``validate_examples.py`` (CI workflows), ``validate_terraform_examples.py`` and
``validate_deploy_terraform.py`` (both via ``opa_terraform_eval.py``), and
``validate_docker_examples.py``. Each had written out the same temp-file /
subprocess / error-handling dance, and ``validate_docker_examples.py`` said so
in its own docstring, waiting for a second consumer before lifting it out.

The per-domain query matters as much as the plumbing, so it lives here too:
every checker must evaluate *only* its own domain's packages, exactly as
``app.services.opa.evaluator`` does in production. The cross-domain aggregate
is deliberately not used, because rules in other domains fire on negations
(a ci_workflow rule asking `not input.name`) that are vacuously true for a
Terraform or Docker document and would report as cross-domain false positives.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[1]
RULES_DIR = ROOT / "backend" / "app" / "rules"
AGGREGATE_REGO = ROOT / "scripts" / "opa" / "aggregate.rego"
OPA_BIN = os.environ.get("OPA_BIN", "opa")

# Severity ordering is shared with the backend seeder and the docs extension.
# app.core.rego_metadata is deliberately stdlib-only so it imports cleanly in
# this environment, which has neither the app nor its dependencies installed.
sys.path.insert(0, str(ROOT / "backend"))
from app.core.rego_metadata import severity_rank as severity_rank  # noqa: E402


def domain_query(domain: str) -> str:
    """Every violation under ``greensecops.<domain>.<category>.<rule>``."""
    return f"[v | v := data.greensecops.{domain}[_][_].violations[_]]"


def run_opa_eval(
    document: Any,
    query: str,
    *,
    with_aggregate: bool = False,
) -> list[Any]:
    """Evaluate ``query`` against ``document`` and return the raw result list.

    ``with_aggregate`` additionally loads ``scripts/opa/aggregate.rego``, which
    only the CI-workflow scoring check needs.
    """
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as handle:
        json.dump(document, handle)
        input_path = handle.name
    cmd = [OPA_BIN, "eval", "-d", str(RULES_DIR)]
    if with_aggregate:
        cmd += ["-d", str(AGGREGATE_REGO)]
    cmd += ["-f", "raw", "-i", input_path, query]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    finally:
        os.unlink(input_path)
    if proc.returncode != 0:
        raise RuntimeError(f"opa eval failed ({query}):\n{proc.stderr.strip()}")
    result: list[Any] = json.loads(proc.stdout or "[]")
    return result


def slugs(violations: list[dict[str, Any]]) -> list[str]:
    """The distinct rule slugs a set of violations tripped, sorted."""
    return sorted({v["rule"] for v in violations})


def load_expected(case_dir: Path, readme: str) -> list[str]:
    """The rule slugs ``case_dir/expected.yaml`` says must fire.

    A case without the file is an error rather than an empty expectation: an
    example nobody wrote expectations for would otherwise silently assert
    "trips no rules at all", which is the strongest claim in the suite.
    """
    expected_file = case_dir / "expected.yaml"
    if not expected_file.exists():
        raise FileNotFoundError(
            f"{case_dir.name}: missing expected.yaml (see {readme})"
        )
    data = YAML(typ="safe").load(expected_file.read_text(encoding="utf-8")) or {}
    return sorted(data.get("violations") or [])


def compare_slugs(expected: list[str], actual: list[str]) -> list[str]:
    """Human-readable complaints about an exact-match mismatch, if any.

    Exact rather than subset: that catches a rule which stopped firing on
    something it should catch *and* one that started firing on something it
    shouldn't, which is the whole point of pinning examples.
    """
    problems = []
    if missing := sorted(set(expected) - set(actual)):
        problems.append(f"expected but not tripped: {', '.join(missing)}")
    if unexpected := sorted(set(actual) - set(expected)):
        problems.append(f"tripped but not expected: {', '.join(unexpected)}")
    return problems
