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

# Per-rule METADATA `good`/`bad` examples are self-testable for every engine
# whose examples are the language it actually analyses, and whose production
# parser turns that language into the OPA input document. That is three of the
# six: ci_workflow (workflow YAML), iac_terraform (HCL) and container_docker
# (Dockerfiles and Compose files).
#
# It used to be one. The stated reason for excluding the other two was that
# their examples "do not parse as executable OPA input" — true of cloud_aws,
# whose examples are illustrative CLI output, and false of the other two, whose
# examples go through `merge_terraform_configs` and `merge_docker_files`
# unchanged. The gap was hiding two live defects: a `good` example that
# violated its own rule, and a `bad` example that did not trigger it. Both are
# exactly what this check exists to catch, and neither was catchable.
#
# ci_telemetry and container_runtime remain excluded: their examples are prose
# sketches of a metrics payload rather than the payload itself.
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
from app.services.docker.merge import merge_docker_files  # noqa: E402
from app.services.terraform.hcl_parser import (
    merge_terraform_configs,  # noqa: E402
)
from app.services.workflow_enrichment import (
    attach_action_metadata,  # noqa: E402
)
from app.services.workflow_parser import (
    parse_workflow_yaml as _parse_yaml,  # noqa: E402
)


def _document(example_yaml: str, action_metadata: dict | None) -> dict:
    """A rule's example snippet as the document OPA would actually evaluate.

    Four rules — impostor_commit, stale_action_ref, ref_version_mismatch,
    archived_action — decide on facts no workflow file contains, which
    production supplies from the GitHub API. Their examples declare those facts
    under ``custom.examples.action_metadata`` and they are attached here through
    the same function production uses, so there is one definition of where
    enrichment lives and the examples stay executable rather than becoming a
    documented exception.

    The fixture is invisible everywhere else: ``rule_registry`` reads ``custom``
    by named keys, and ``rego_autodoc`` renders only bad/good/fix, so it neither
    seeds nor appears on the published rule page.
    """
    document = _parse_yaml(example_yaml)
    if document is not None:
        attach_action_metadata(document, action_metadata)
    return document


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

        action_metadata = examples.get("action_metadata")

        good = examples.get("good")
        if good:
            self_hits = run_opa_eval(_document(good, action_metadata), query)
            if self_hits:
                errors.append(
                    f"{category}/{name}: 'good' example violates its own rule "
                    f"({len(self_hits)} violation(s)) — a compliant example must pass."
                )

        bad = examples.get("bad")
        if bad:
            self_hits = run_opa_eval(_document(bad, action_metadata), query)
            if not self_hits:
                errors.append(
                    f"{category}/{name}: 'bad' example does not trigger its own rule "
                    "— a non-compliant example must demonstrate the violation."
                )
    return errors


def _terraform_document(files: dict[str, str]) -> dict:
    return merge_terraform_configs(list(files.items()))


def _docker_document(files: dict[str, str]) -> dict:
    return merge_docker_files(list(files.items()))


def _default_filename(domain: str, slug: str, snippet: str) -> str:
    """The filename a single-snippet example is evaluated under.

    It is load-bearing for Docker: ``merge.classify_docker_file`` decides
    whether a snippet is a Dockerfile or a Compose file from its *name*, and a
    Compose rule reading `input.compose_files` sees nothing if its example was
    filed as a Dockerfile.
    """
    if domain == "iac_terraform":
        return "main.tf"
    if slug.startswith("compose") or snippet.lstrip().startswith(
        ("services:", "version:", "name:")
    ):
        return "compose.yml"
    return "Dockerfile"


def _example_files(examples: dict, kind: str, domain: str, slug: str) -> dict[str, str]:
    """The files one direction of an example is evaluated as.

    ``bad_files``/``good_files`` map filename to content, for the rules whose
    subject is a *relationship between* files — the four ``compose_override_*``
    rules compare a base against its override, and a single snippet cannot
    express that. Everything else uses the plain ``bad``/``good`` snippet the
    docs render, under a derived filename.
    """
    multi = examples.get(f"{kind}_files")
    if multi:
        return dict(multi)
    snippet = examples.get(kind)
    if not snippet:
        return {}
    return {_default_filename(domain, slug, snippet): snippet}


def check_parsed_domain_examples(domain: str, build) -> list[str]:
    """``good`` must not fire, ``bad`` must, for one non-workflow engine."""
    errors: list[str] = []
    for rego in sorted((RULES_DIR / domain).glob("*/*.rego")):
        if rego.name.endswith("_test.rego"):
            continue
        category, name = rego.parent.name, rego.stem
        examples = (_parse_metadata(rego).get("custom") or {}).get("examples") or {}
        query = f"data.greensecops.{domain}.{category}.{name}.violations"

        for kind in ("good", "bad"):
            files = _example_files(examples, kind, domain, name)
            if not files:
                continue
            hits = run_opa_eval(build(files), query)
            if kind == "good" and hits:
                errors.append(
                    f"{domain}/{category}/{name}: 'good' example violates its own rule "
                    f"({len(hits)} violation(s)) — a compliant example must pass."
                )
            if kind == "bad" and not hits:
                errors.append(
                    f"{domain}/{category}/{name}: 'bad' example does not trigger its "
                    "own rule — a non-compliant example must demonstrate the violation."
                )
    return errors


def main() -> int:
    errors = (
        check_canonical_examples()
        + check_rule_metadata_examples()
        + check_parsed_domain_examples("iac_terraform", _terraform_document)
        + check_parsed_domain_examples("container_docker", _docker_document)
    )
    if errors:
        print("Example validation FAILED:\n", file=sys.stderr)
        for err in errors:
            print(f"  ✗ {err}", file=sys.stderr)
        print(f"\n{len(errors)} problem(s) found.", file=sys.stderr)
        return 1
    print("All rule examples validated against the OPA rule suite ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
