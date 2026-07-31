#!/usr/bin/env python3
"""Validate the shipped Docker examples against the full OPA rule suite.

Run in CI (``.github/workflows/opa.yml``) and locally. The Docker counterpart to
``scripts/validate_terraform_examples.py``: every case under
``examples/docker/<case>/`` is parsed and merged exactly as production does
(``app.services.docker.merge.merge_docker_files``), evaluated against the full
``container_docker`` rule suite, and its tripped rule slugs are asserted to
match the case's ``expected.yaml`` **exactly**. An exact match catches both a
rule that stopped firing on a file it should catch (a regression) and a rule
that started firing on a file it shouldn't (a false positive) as the ruleset
evolves.

Adding a new case is intentionally a no-code operation: drop a folder under
``examples/docker/`` containing any mix of Dockerfiles and Compose files plus an
``expected.yaml``, and it is picked up automatically. See
``examples/docker/README.md``.

Unlike the Terraform validators, the parse/merge/eval pipeline is inline rather
than in a shared module: there is exactly one consumer today. Should a second
appear (the deployment self-scan equivalent of
``scripts/validate_deploy_terraform.py``), lift it into
``scripts/opa_docker_eval.py`` the way the Terraform pair did.
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
OPA_BIN = os.environ.get("OPA_BIN", "opa")
EXAMPLES_DIR = ROOT / "examples" / "docker"

# Evaluate ONLY the container_docker packages, exactly like production's
# app.services.opa.evaluator.evaluate_docker. The cross-domain aggregate is
# deliberately not used: rules in other domains fire on negations (e.g.
# ci_workflow's `not input.name`) that are vacuously true for a Docker
# document and would show up as cross-domain false positives.
DOCKER_VIOLATIONS_QUERY = "[v | v := data.greensecops.container_docker[_][_].violations[_]]"

# Reuse the exact parse+merge production feeds to OPA rather than
# re-implementing Dockerfile/Compose handling here.
sys.path.insert(0, str(ROOT / "backend"))
from app.services.docker.merge import (  # noqa: E402
    classify_docker_file,
    merge_docker_files,
)


def collect_docker_files(directory: Path) -> list[tuple[str, str]]:
    """Collect the case's Docker files as the (path, content) pairs OPA needs.

    Paths are relative to ``directory`` so a reported ``file_path`` reads the
    same whoever runs the check. Recursive, because a realistic case puts a
    Dockerfile in a subdirectory and references it from a Compose ``build``.
    """
    files = sorted(
        p
        for p in directory.glob("**/*")
        if p.is_file() and classify_docker_file(p.name) is not None
    )
    return [
        (p.relative_to(directory).as_posix(), p.read_text(encoding="utf-8"))
        for p in files
    ]


def evaluate_violations(merged: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every ``container_docker`` violation ``merged`` trips."""
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as handle:
        json.dump(merged, handle)
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
        DOCKER_VIOLATIONS_QUERY,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    finally:
        os.unlink(input_path)
    if proc.returncode != 0:
        raise RuntimeError(f"opa eval failed:\n{proc.stderr.strip()}")
    violations: list[dict[str, Any]] = json.loads(proc.stdout or "[]")
    return violations


def unparseable_files(files: list[tuple[str, str]]) -> list[str]:
    """Return the paths in ``files`` the parsers cannot read.

    ``merge_docker_files`` skips a file it cannot parse rather than aborting —
    right in production, where one bad file should not lose every other file's
    findings, but wrong in a check whose job is to assert an exact rule set: a
    silently unscanned file makes the case pass for the wrong reason.
    """
    merged = merge_docker_files(files)
    parsed = {d["__docker_file"] for d in merged["dockerfiles"]}
    parsed |= {c["__docker_file"] for c in merged["compose_files"]}
    return [path for path, _ in files if path not in parsed]


def _load_expected(case_dir: Path) -> list[str]:
    expected_file = case_dir / "expected.yaml"
    if not expected_file.exists():
        raise FileNotFoundError(
            f"{case_dir.name}: missing expected.yaml (see examples/docker/README.md)"
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
        print(f"No Docker examples directory at {EXAMPLES_DIR}", file=sys.stderr)
        return 1

    errors: list[str] = []
    checked = 0
    for case_dir in sorted(p for p in EXAMPLES_DIR.iterdir() if p.is_dir()):
        docker_files = collect_docker_files(case_dir)
        if not docker_files:
            errors.append(f"{case_dir.name}: no Dockerfile or Compose file found")
            continue
        unparseable = unparseable_files(docker_files)
        if unparseable:
            errors.append(f"{case_dir.name}: unparseable file(s): {unparseable}")
            continue
        try:
            expected = _load_expected(case_dir)
        except FileNotFoundError as exc:
            errors.append(str(exc))
            continue
        tripped = sorted({v["rule"] for v in evaluate_violations(merge_docker_files(docker_files))})
        checked += 1
        if tripped != expected:
            errors.append(_describe_mismatch(case_dir.name, expected, tripped))

    if errors:
        print("Docker example validation FAILED:\n", file=sys.stderr)
        for err in errors:
            print(f"  ✗ {err}", file=sys.stderr)
        print(f"\n{len(errors)} problem(s) found.", file=sys.stderr)
        return 1
    print(f"All {checked} Docker example(s) validated against the OPA rule suite ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
