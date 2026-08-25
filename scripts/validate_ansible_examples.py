#!/usr/bin/env python3
"""Validate the shipped Ansible examples against the full OPA rule suite.

Run in CI (``.github/workflows/opa.yml``) and locally. The Ansible counterpart
to ``scripts/validate_docker_examples.py``: every case under
``examples/ansible/<case>/`` is collected and parsed exactly as production does
(``app.services.ansible.parser.merge_ansible_files``), evaluated against the
full ``iac_ansible`` rule suite, and its tripped rule slugs are asserted to
match the case's ``expected.yaml`` **exactly**. An exact match catches both a
rule that stopped firing on content it should catch and one that started firing
on content it should not, as the ruleset evolves.

Adding a new case is intentionally a no-code operation: drop a folder under
``examples/ansible/`` containing a playbook, a role tree, a galaxy file or any
mix of them plus an ``expected.yaml``, and it is picked up automatically. See
``examples/ansible/README.md``.

The clean case matters as much as the bad one. A rule that fires on
``web-role-hardened/`` is producing noise on content that is already correct,
and the build fails for it.
"""

from __future__ import annotations

import sys
from pathlib import Path

from opa_ansible_eval import collect_ansible_files, evaluate_violations
from opa_eval import ROOT, compare_slugs, load_expected, slugs

EXAMPLES_DIR = ROOT / "examples" / "ansible"

README = "examples/ansible/README.md"


def main() -> int:
    if not EXAMPLES_DIR.is_dir():
        print(f"No Ansible examples directory at {EXAMPLES_DIR}", file=sys.stderr)
        return 1

    cases = sorted(p for p in EXAMPLES_DIR.iterdir() if (p / "expected.yaml").is_file())
    if not cases:
        print(f"No Ansible example cases under {EXAMPLES_DIR}", file=sys.stderr)
        return 1

    failures = 0
    for case in cases:
        files = collect_ansible_files(case)
        if not files:
            print(f"✗ {case.name}: no Ansible files found", file=sys.stderr)
            failures += 1
            continue

        expected = load_expected(case, README)
        actual = slugs(evaluate_violations(files))
        problems = compare_slugs(expected, actual)
        if problems:
            failures += 1
            print(f"✗ {case.name} ({len(files)} file(s))", file=sys.stderr)
            for problem in problems:
                print(f"    {problem}", file=sys.stderr)
        else:
            print(f"✓ {case.name} ({len(files)} file(s), {len(actual)} rule(s))")

    if failures:
        print(
            f"\n{failures} Ansible example case(s) do not match their expected.yaml",
            file=sys.stderr,
        )
        return 1
    print(f"\nAll {len(cases)} Ansible example case(s) match ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
