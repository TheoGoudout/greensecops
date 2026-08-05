#!/usr/bin/env python3
"""Scan GreenSecOps's own AWS deployment Terraform with GreenSecOps's own rules.

Run in CI (``.github/workflows/opa.yml``) and from the ``deploy-terraform-opa``
pre-commit hook. Every ``.tf`` / ``.tf.json`` file under ``deploy/terraform/``
is parsed and merged exactly as production does, evaluated against the full
``iac_terraform`` rule suite, and the check **fails on any violation at all**.

That zero-violation bar is the point: the reference deployment of a product
that sells Terraform scanning has to be one its own ruleset passes. This is
deliberately stricter than ``scripts/validate_terraform_examples.py``, whose
example modules assert an exact *expected* set of violations because several
of them exist precisely to demonstrate a finding.

The whole tree is merged into one document rather than scanned per directory:
that mirrors the recursive fetcher in production, which merges a repository's
root and its submodules together, so a finding inside ``modules/`` is still
attributed to its own file via ``file_path``.
"""

from __future__ import annotations

import sys
from typing import Any

from opa_eval import severity_rank
from opa_terraform_eval import (
    ROOT,
    collect_tf_files,
    evaluate_violations,
    merge_terraform_configs,
    unparseable_files,
)

DEPLOY_TF_DIR = ROOT / "deploy" / "terraform"

def _sort_key(violation: dict[str, Any]) -> tuple[int, str, str]:
    return (
        severity_rank(str(violation.get("severity", ""))),
        str(violation.get("file_path", "")),
        str(violation.get("resource_address", "")),
    )


def _format(violation: dict[str, Any]) -> str:
    location = violation.get("file_path") or "<unknown file>"
    start, end = violation.get("line_start"), violation.get("line_end")
    if start is not None:
        location += f":{start}" + (
            f"-{end}" if end is not None and end != start else ""
        )
    return (
        f"  ✗ [{violation.get('severity', '?')}] {violation.get('rule', '?')} "
        f"— {violation.get('resource_address', '?')} ({location})\n"
        f"      {violation.get('message', '').strip()}"
    )


def main() -> int:
    if not DEPLOY_TF_DIR.is_dir():
        print(f"No deployment Terraform directory at {DEPLOY_TF_DIR}", file=sys.stderr)
        return 1

    tf_files = collect_tf_files(DEPLOY_TF_DIR, recursive=True)
    if not tf_files:
        print(f"No .tf/.tf.json files found under {DEPLOY_TF_DIR}", file=sys.stderr)
        return 1

    # A file the parser cannot read is a file that is not scanned. Without this
    # the check would report "violation-free" while silently skipping it.
    unparseable = unparseable_files(tf_files)
    if unparseable:
        print(
            "Deployment Terraform could not be fully parsed, so the scan would "
            "have skipped these file(s) rather than checking them:\n",
            file=sys.stderr,
        )
        for path in unparseable:
            print(f"  ✗ {path}", file=sys.stderr)
        return 1

    violations = evaluate_violations(merge_terraform_configs(tf_files))
    if violations:
        print(
            "Deployment Terraform FAILED the GreenSecOps rule suite "
            f"({len(violations)} violation(s)):\n",
            file=sys.stderr,
        )
        for violation in sorted(violations, key=_sort_key):
            print(_format(violation), file=sys.stderr)
        print(
            "\nThe deployment config must stay violation-free — fix the resource, "
            "or fix the rule if this is a false positive.",
            file=sys.stderr,
        )
        return 1

    print(
        f"Deployment Terraform ({len(tf_files)} file(s)) is violation-free "
        "against the GreenSecOps rule suite ✅"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
