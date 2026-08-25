#!/usr/bin/env python3
"""Scan GreenSecOps's own deployment playbooks with GreenSecOps's own rules.

Run in CI (``.github/workflows/opa.yml``) and from the ``deploy-ansible-opa``
pre-commit hook. Every Ansible file under ``deploy/ansible/`` is collected and
parsed exactly as production does, evaluated against the full ``iac_ansible``
rule suite, and the check **fails on any violation at all**.

That zero-violation bar is the point, and it is the same bar
``validate_deploy_terraform.py`` holds Terraform to: the reference deployment of
a product that sells Ansible scanning has to be one its own ruleset passes. It
is deliberately stricter than ``validate_ansible_examples.py``, whose cases
assert an exact *expected* set because several of them exist to demonstrate a
finding.

``ansible-lint`` already runs over the same tree from its own pre-commit hook.
This is not a substitute: the two ask different questions, and the axes this
suite grades — repeated work, unverified downloads, credentials in source — are
mostly not ones a linter covers.
"""

from __future__ import annotations

import sys
from typing import Any

from opa_ansible_eval import collect_ansible_files, evaluate_violations
from opa_eval import ROOT, severity_rank

DEPLOY_ANSIBLE_DIR = ROOT / "deploy" / "ansible"


def _sort_key(violation: dict[str, Any]) -> tuple[int, str, int]:
    return (
        severity_rank(str(violation.get("severity", ""))),
        str(violation.get("file_path", "")),
        int(violation.get("line_start") or 0),
    )


def _format(violation: dict[str, Any]) -> str:
    location = violation.get("file_path") or "<unknown file>"
    start, end = violation.get("line_start"), violation.get("line_end")
    if start is not None:
        location += f":{start}" + (
            f"-{end}" if end is not None and end != start else ""
        )
    subject = violation.get("task_name") or violation.get("discriminator") or "?"
    return (
        f"  ✗ [{violation.get('severity', '?')}] {violation.get('rule', '?')} "
        f"— {subject} ({location})\n"
        f"      {violation.get('message', '').strip()}"
    )


def main() -> int:
    if not DEPLOY_ANSIBLE_DIR.is_dir():
        print(f"No deployment Ansible directory at {DEPLOY_ANSIBLE_DIR}", file=sys.stderr)
        return 1

    files = collect_ansible_files(DEPLOY_ANSIBLE_DIR)
    if not files:
        print(f"No Ansible files found under {DEPLOY_ANSIBLE_DIR}", file=sys.stderr)
        return 1

    violations = evaluate_violations(files)
    if violations:
        print(
            f"{len(violations)} violation(s) in the deployment playbooks "
            f"({len(files)} file(s) scanned):\n",
            file=sys.stderr,
        )
        for violation in sorted(violations, key=_sort_key):
            print(_format(violation), file=sys.stderr)
        print(
            "\nThe reference deployment has to pass the rules the product ships.",
            file=sys.stderr,
        )
        return 1

    print(f"deploy/ansible/ is clean against the iac_ansible suite ✅ ({len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
