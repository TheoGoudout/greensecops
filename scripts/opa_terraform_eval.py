"""Shared OPA evaluation for the repo's Terraform validators.

Both ``scripts/validate_terraform_examples.py`` (which asserts an *exact* set of
tripped rules per example) and ``scripts/validate_deploy_terraform.py`` (which
asserts *zero* violations on the project's own deployment config) need the same
thing: parse a directory of Terraform files exactly as production does and hand
the result to OPA. That parse+merge+eval pipeline lives here so the two can
never drift apart — an example that passes and a deployment that passes are
then genuinely evaluated the same way.

Parsing reuses the production code path
(``app.services.terraform.hcl_parser.merge_terraform_configs``), so anything
these scripts accept is faithful to what a real scan of the same files sees:
identical ``__tf_file`` tagging and per-block-type list-concatenation feed OPA.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RULES_DIR = ROOT / "backend" / "app" / "rules"
OPA_BIN = os.environ.get("OPA_BIN", "opa")

# Evaluate ONLY the iac_terraform packages, exactly like production's
# app.services.opa.evaluator.evaluate_terraform. The cross-domain aggregate is
# deliberately not used here: some ci_workflow rules fire on a negation (e.g.
# `not input.name`), which is vacuously true for a Terraform document and would
# be a cross-domain false positive. This comprehension collects every violation
# under greensecops.iac_terraform.<category>.<rule> and nothing else.
TERRAFORM_VIOLATIONS_QUERY = (
    "[v | v := data.greensecops.iac_terraform[_][_].violations[_]]"
)

# Reuse the exact parse+merge production feeds to OPA rather than
# re-implementing HCL handling here.
sys.path.insert(0, str(ROOT / "backend"))
from app.services.terraform.hcl_parser import (  # noqa: E402
    merge_terraform_configs,
    parse_terraform_content,
)

__all__ = [
    "OPA_BIN",
    "RULES_DIR",
    "ROOT",
    "collect_tf_files",
    "evaluate_violations",
    "merge_terraform_configs",
    "unparseable_files",
]


def unparseable_files(files: list[tuple[str, str]]) -> list[str]:
    """Return the paths in ``files`` that the HCL parser cannot read.

    ``merge_terraform_configs`` skips a file it cannot parse rather than
    aborting the whole scan — the right behaviour in production, where one bad
    file in a customer repository should not lose the findings from every other
    one. In a check whose whole job is to prove a directory is clean it is the
    wrong behaviour: an unparseable file is silently *not scanned*, and the
    check passes for the wrong reason. Callers use this to fail loudly instead.
    """
    return [
        path
        for path, content in files
        if parse_terraform_content(path, content) is None
    ]


def evaluate_violations(merged_config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every ``iac_terraform`` violation ``merged_config`` trips.

    Violations come back as the full dicts the Rego rules emit (rule, severity,
    category, resource_address, file_path, line_start, line_end, message), so
    callers can either report them in detail or reduce them to slugs.
    """
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
        TERRAFORM_VIOLATIONS_QUERY,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    finally:
        os.unlink(input_path)
    if proc.returncode != 0:
        raise RuntimeError(f"opa eval failed:\n{proc.stderr.strip()}")
    violations: list[dict[str, Any]] = json.loads(proc.stdout or "[]")
    return violations


def collect_tf_files(
    directory: Path, *, recursive: bool = False
) -> list[tuple[str, str]]:
    """Collect ``.tf`` / ``.tf.json`` files as the (path, content) pairs OPA needs.

    Paths are relative to ``directory`` so a reported ``file_path`` reads the
    same whoever runs the check. ``recursive`` walks a whole module tree —
    Terraform itself only treats one directory as a module, but the scanner
    merges a tree the same way production's recursive fetcher does, so a
    finding in a submodule is still attributed to its own file.
    """
    pattern = "**/*" if recursive else "*"
    files = sorted(
        p
        for p in directory.glob(pattern)
        if p.is_file() and (p.suffix == ".tf" or p.name.endswith(".tf.json"))
    )
    return [
        (p.relative_to(directory).as_posix(), p.read_text(encoding="utf-8"))
        for p in files
    ]
