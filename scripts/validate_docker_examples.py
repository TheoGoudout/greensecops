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

The parse/merge half is inline (there is one consumer); the eval half lives in
``scripts/opa_eval.py``, shared with every other checker so none of them can
drift on how OPA is invoked.
"""

from __future__ import annotations

import sys
from pathlib import Path

from opa_eval import (
    ROOT,
    compare_slugs,
    domain_query,
    load_expected,
    run_opa_eval,
    slugs,
)

EXAMPLES_DIR = ROOT / "examples" / "docker"

DOCKER_VIOLATIONS_QUERY = domain_query("container_docker")

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
            expected = load_expected(case_dir, "examples/docker/README.md")
        except FileNotFoundError as exc:
            errors.append(str(exc))
            continue
        tripped = slugs(
            run_opa_eval(merge_docker_files(docker_files), DOCKER_VIOLATIONS_QUERY)
        )
        checked += 1
        if problems := compare_slugs(expected, tripped):
            errors.append(f"{case_dir.name}: " + "; ".join(problems))

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
