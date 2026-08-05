"""Integration tests for terraform_analysis against real-world Terraform modules.

The rest of the Terraform suite runs on HCL invented for the test
(``resource "x" "y" {}``). This module runs on Terraform vendored verbatim from
public repositories — bridgecrewio/terragoat and two terraform-aws-modules
registry modules — so a parse or pipeline regression that only shows up on
configuration people actually write fails the build. See
``tests/fixtures/terraform/README.md`` for the corpus and its provenance.

The parse, merge, ``__tf_file`` tagging, line spans, fingerprinting, persistence
and scoring are all real. Only OPA is mocked: the backend test environment ships
no ``opa`` binary, so each case's ``expected.json`` carries violations *recorded*
from the live rule suite (``scripts/regenerate_terraform_fixtures.py``) and
``_evaluate`` replays them — the same arrangement
``test_static_analysis_integration.py`` uses for workflows.

Adding a case is a no-code operation: drop a folder of ``.tf`` files into
``tests/fixtures/terraform/`` and regenerate its ``expected.json``. The
parametrized tests below discover it automatically.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, col, select

from app.models import (
    FindingStatus,
    Organization,
    Repository,
    Rule,
    RuleDomain,
    TerraformFinding,
    TerraformRoot,
    UserTier,
)
from app.services.opa.evaluator import TerraformOpaViolation
from app.services.terraform.hcl_parser import (
    derive_module_path,
    merge_terraform_configs,
    parse_terraform_content,
)
from app.workers.tasks.terraform_analysis import _run_terraform_scan_impl

# ─── Corpus loading ───────────────────────────────────────────────────────────

_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "terraform"

# Every vendored root module, discovered rather than listed.
_CASES = sorted(p.name for p in _FIXTURES.iterdir() if (p / "expected.json").is_file())

# The case that trips rules; the other two are hardened modules that trip
# nothing. Named here so the violation-side tests read concretely instead of
# hunting through the corpus for one with findings.
_TERRAGOAT = "terragoat_aws"


def _case_files(case: str) -> list[tuple[str, str]]:
    """A case's files as the ``(path, content)`` pairs ``merge_terraform_configs`` takes."""
    return [
        (p.name, p.read_text())
        for p in sorted((_FIXTURES / case).iterdir())
        if p.name.endswith((".tf", ".tf.json"))
    ]


def _expected(case: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(
        (_FIXTURES / case / "expected.json").read_text()
    )
    return payload


@dataclass
class FakeTerraformFile:
    path: str
    content: str
    content_hash: str = ""
    sha: str = ""


def _rooted(
    case: str, root_path: str, subdir: str = ""
) -> tuple[list[FakeTerraformFile], list[TerraformOpaViolation]]:
    """Place a case inside a repository, as the fetcher would hand it over.

    ``fetch_terraform_files`` returns repo-relative paths, so a root at
    ``infra/prod`` yields ``infra/prod/main.tf`` — and OPA echoes that same path
    back through ``__tf_file``. Prefixing both keeps the fetched files and the
    recorded violations consistent, which is what ``derive_module_path`` reads.
    """
    prefix = "/".join(part for part in (root_path, subdir) if part)
    files = [
        FakeTerraformFile(
            path=f"{prefix}/{name}", content=content, content_hash=uuid.uuid4().hex
        )
        for name, content in _case_files(case)
    ]
    violations = [
        TerraformOpaViolation(
            rule_slug=violation["rule_slug"],
            severity=violation["severity"],
            category=violation["category"],
            message=violation["message"],
            resource_address=violation["resource_address"],
            file_path=f"{prefix}/{violation['file_path']}",
            line_start=violation["line_start"],
            line_end=violation["line_end"],
        )
        for violation in _expected(case)["violations"]
    ]
    return files, violations


def _patch_fetch(files: list[FakeTerraformFile]) -> Any:
    return patch(
        "app.workers.tasks.terraform_analysis._fetch_terraform_files",
        return_value=files,
    )


def _patch_evaluate(violations: list[TerraformOpaViolation]) -> Any:
    return patch(
        "app.workers.tasks.terraform_analysis._evaluate",
        new=AsyncMock(return_value=violations),
    )


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"tf-integ-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture()
def repo(db: Session, org: Organization) -> Repository:
    repository = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"tf-integ/repo-{uuid.uuid4().hex[:8]}",
        installation_id=30001,
        default_branch="main",
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@pytest.fixture()
def terraform_root(db: Session, repo: Repository) -> TerraformRoot:
    root = TerraformRoot(repo_id=repo.id, root_path=f"infra/{uuid.uuid4().hex[:8]}")
    db.add(root)
    db.commit()
    db.refresh(root)
    return root


def _findings(db: Session, root: TerraformRoot) -> list[TerraformFinding]:
    return list(
        db.exec(
            select(TerraformFinding).where(
                TerraformFinding.terraform_root_id == root.id
            )
        ).all()
    )


# ══════════════════════════════════════════════════════════════════════════════
# Parse and merge over the real corpus — no DB, no mocking, exact assertions
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("case", _CASES)
def test_every_vendored_file_parses(case: str) -> None:
    """No file in the corpus falls back to the ``None`` parse-error path."""
    files = _case_files(case)
    assert files, f"{case}: no .tf files vendored"
    unparseable = [
        name
        for name, content in files
        if parse_terraform_content(name, content) is None
    ]
    assert unparseable == [], f"{case}: failed to parse {unparseable}"


# Block types whose named entries carry an attrs dict, and so get a __tf_file
# tag. `locals` and `terraform` are deliberately absent: their values are
# scalars and lists (`create = ...`, `backend "s3" {...}`), there is no attrs
# dict to stamp, and no rule reads them.
_TAGGED_BLOCK_TYPES = ("resource", "data", "variable", "module", "provider", "output")


def _owned_blocks(file_name: str, content: str) -> dict[tuple[str, ...], str]:
    """Identity → source file for every taggable block declared in one file."""
    parsed = parse_terraform_content(file_name, content)
    assert parsed is not None, f"{file_name} failed to parse"
    owners: dict[tuple[str, ...], str] = {}
    for key in _TAGGED_BLOCK_TYPES:
        value = parsed.get(key)
        if value is None:
            continue
        for block in value if isinstance(value, list) else [value]:
            if not isinstance(block, dict):
                continue
            for label, inner in block.items():
                if not isinstance(inner, dict):
                    continue
                if key in ("resource", "data"):
                    for resource_name in inner:
                        owners[(key, label, resource_name)] = file_name
                else:
                    owners[(key, label)] = file_name
    return owners


@pytest.mark.parametrize("case", _CASES)
def test_merge_tags_every_block_with_the_file_it_came_from(case: str) -> None:
    """``__tf_file`` on a real multi-file root names the file the block is really in.

    Derived from the fixtures rather than hardcoded: each file is parsed alone to
    learn which blocks it declares, then the merged config must agree. This
    covers both nesting shapes at once — ``resource``/``data`` nest one level
    deeper than ``variable``/``module``/``provider``/``output``, a distinction
    that once silently left the shallower ones untagged.
    """
    files = _case_files(case)
    merged = merge_terraform_configs(files)

    expected_owner: dict[tuple[str, ...], str] = {}
    for name, content in files:
        expected_owner.update(_owned_blocks(name, content))
    assert expected_owner, f"{case}: parsed no taggable blocks"

    for identity, source_file in expected_owner.items():
        for block in merged[identity[0]]:
            attrs: Any = block
            for part in identity[1:]:
                attrs = attrs.get(part) if isinstance(attrs, dict) else None
            if isinstance(attrs, dict) and attrs.get("__tf_file") == source_file:
                break
        else:
            raise AssertionError(
                f"{case}: {'.'.join(identity)} is not tagged {source_file!r} "
                "after the merge"
            )


@pytest.mark.parametrize("case", _CASES)
def test_line_spans_fall_inside_their_real_source_file(case: str) -> None:
    """``with_meta`` spans on real blocks are 1-based, ordered, and in range."""
    files = dict(_case_files(case))
    line_counts = {name: len(content.splitlines()) for name, content in files.items()}
    merged = merge_terraform_configs(list(files.items()))

    spans_checked = 0
    for blocks in merged.values():
        for block in blocks:
            if not isinstance(block, dict):
                continue
            for named in block.values():
                for attrs in _attr_dicts(named):
                    start = attrs.get("__start_line__")
                    end = attrs.get("__end_line__")
                    if start is None or end is None:
                        continue
                    source = attrs["__tf_file"]
                    assert 1 <= start <= end <= line_counts[source], (
                        f"{case}: span {start}-{end} outside {source} "
                        f"({line_counts[source]} lines)"
                    )
                    spans_checked += 1
    assert spans_checked > 0, f"{case}: no line spans stamped"


def _attr_dicts(named: Any) -> list[dict[str, Any]]:
    """The attrs dicts under a block label, whichever nesting depth it uses."""
    if not isinstance(named, dict):
        return []
    if "__tf_file" in named:
        return [named]
    return [inner for inner in named.values() if isinstance(inner, dict)]


def test_terragoat_security_group_ingress_survives_the_merge() -> None:
    """The two world-open ingress blocks are still there for a rule to see.

    hcl2 parses repeated nested blocks into a list; losing that would silently
    hide the second violation the rule suite records for this resource.
    """
    merged = merge_terraform_configs(_case_files(_TERRAGOAT))
    security_groups = [
        attrs
        for block in merged["resource"]
        if "aws_security_group" in block
        for attrs in block["aws_security_group"].values()
    ]
    web_node = next(
        sg for sg in security_groups if sg["__tf_file"] == "ec2.tf" and "ingress" in sg
    )
    open_ports = sorted(
        ingress["from_port"]
        for ingress in web_node["ingress"]
        if "0.0.0.0/0" in ingress["cidr_blocks"]
    )
    assert open_ports == [22, 80]


def test_derive_module_path_over_a_real_nested_module_layout() -> None:
    """A vendored case placed in a subdirectory is attributed to that directory."""
    root_path = "infra/prod"
    for name, _ in _case_files("terraform_aws_security_group"):
        assert (
            derive_module_path(f"{root_path}/modules/security_group/{name}", root_path)
            == "modules/security_group"
        )
        assert derive_module_path(f"{root_path}/{name}", root_path) is None


# ══════════════════════════════════════════════════════════════════════════════
# Full scan pipeline over the real corpus — DB + replayed violations
# ══════════════════════════════════════════════════════════════════════════════


def test_terragoat_scan_persists_real_addresses_and_files(
    db: Session, terraform_root: TerraformRoot
) -> None:
    """Findings carry the resource addresses and paths that exist in the module."""
    files, violations = _rooted(_TERRAGOAT, terraform_root.root_path)
    with _patch_fetch(files), _patch_evaluate(violations):
        result = _run_terraform_scan_impl(str(terraform_root.id))

    assert result["status"] == "done"
    findings = _findings(db, terraform_root)
    assert {f.resource_address for f in findings} == {
        "aws_instance.web_host",
        "aws_lambda_function.analysis_lambda",
        "aws_security_group.web-node",
        "aws_db_instance.default",
        "aws_s3_bucket.data",
        "aws_s3_bucket.data_science",
        "aws_s3_bucket.financials",
        "aws_s3_bucket.flowbucket",
        "aws_s3_bucket.logs",
        "aws_s3_bucket.operations",
        "aws_ebs_volume.web_host_storage",
    }
    fetched_paths = {f.path for f in files}
    assert {f.file_path for f in findings} <= fetched_paths
    # Every file lives directly in the root, so nothing gets a module prefix.
    assert all(f.module_path is None for f in findings)
    assert all(f.terraform_address == f.resource_address for f in findings)


def test_terragoat_scan_degrades_the_score(
    db: Session,  # noqa: ARG001
    terraform_root: TerraformRoot,
) -> None:
    """A real insecure estate cannot come out clean."""
    files, violations = _rooted(_TERRAGOAT, terraform_root.root_path)
    with _patch_fetch(files), _patch_evaluate(violations):
        result = _run_terraform_scan_impl(str(terraform_root.id))

    score = result["score"]
    assert isinstance(score, float)
    assert score < 100.0
    assert result["grade"] != "A+++"


def test_one_security_group_open_on_two_ports_is_one_finding(
    db: Session, terraform_root: TerraformRoot
) -> None:
    """terragoat's ``web-node`` trips the ingress rule twice — 22 and 80 — but a
    finding's fingerprint keys on (root, rule, resource_address), so the two
    collapse into a single row. The task's returned ``findings`` count is a
    violation count, so it stays at the higher number; the DB is the deduplicated
    view. Real code is what surfaces the difference — invented one-violation
    fixtures never do.
    """
    files, violations = _rooted(_TERRAGOAT, terraform_root.root_path)
    ingress = [v for v in violations if v.rule_slug == "open_ingress_security_group"]
    assert len(ingress) == 2, "fixture no longer has the two-port security group"
    assert len({v.resource_address for v in ingress}) == 1

    with _patch_fetch(files), _patch_evaluate(violations):
        result = _run_terraform_scan_impl(str(terraform_root.id))

    assert result["findings"] == len(violations)
    rows = [
        f
        for f in _findings(db, terraform_root)
        if f.resource_address == ingress[0].resource_address
    ]
    assert len(rows) == 1
    assert _expected(_TERRAGOAT)["expected_finding_count"] == len(
        _findings(db, terraform_root)
    )


def test_terragoat_in_a_submodule_directory_gets_a_module_prefix(
    db: Session, terraform_root: TerraformRoot
) -> None:
    """The same real module one directory down is addressed through its module path."""
    files, violations = _rooted(
        _TERRAGOAT, terraform_root.root_path, subdir="modules/legacy_aws"
    )
    with _patch_fetch(files), _patch_evaluate(violations):
        _run_terraform_scan_impl(str(terraform_root.id))

    findings = _findings(db, terraform_root)
    assert findings
    assert all(f.module_path == "modules/legacy_aws" for f in findings)
    assert all(
        f.terraform_address == f"module.modules.legacy_aws.{f.resource_address}"
        for f in findings
    )


def test_hardening_a_real_module_resolves_its_findings(
    db: Session, terraform_root: TerraformRoot
) -> None:
    """terragoat scanned, then replaced by a hardened module: every finding resolves."""
    bad_files, bad_violations = _rooted(_TERRAGOAT, terraform_root.root_path)
    with _patch_fetch(bad_files), _patch_evaluate(bad_violations):
        _run_terraform_scan_impl(str(terraform_root.id))
    assert _findings(db, terraform_root)

    good_files, good_violations = _rooted(
        "terraform_aws_security_group", terraform_root.root_path
    )
    assert good_violations == [], "the hardened case is expected to trip nothing"
    with _patch_fetch(good_files), _patch_evaluate(good_violations):
        result = _run_terraform_scan_impl(str(terraform_root.id))

    assert result["score"] == 100.0
    assert result["grade"] == "A+++"
    findings = _findings(db, terraform_root)
    assert findings
    assert all(f.status == FindingStatus.resolved for f in findings)
    assert all(f.resolved_at is not None for f in findings)


# ══════════════════════════════════════════════════════════════════════════════
# Auto-discovered scenarios
#
# Drop a folder of real .tf files into tests/fixtures/terraform/ and regenerate
# its expected.json (scripts/regenerate_terraform_fixtures.py). Picked up here
# automatically — no code changes needed.
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("case", _CASES)
def test_recorded_violations_still_point_at_the_vendored_code(case: str) -> None:
    """Guard against an ``expected.json`` drifting away from the files it describes.

    Every recorded violation must name a file the case actually ships and a
    resource address the config actually declares. Re-vendoring at a newer
    upstream commit without regenerating fails here.
    """
    expected = _expected(case)
    files = _case_files(case)
    assert expected["files"] == [name for name, _ in files]

    merged = merge_terraform_configs(files)
    declared = {
        f"{resource_type}.{name}"
        for block in merged.get("resource", [])
        for resource_type, named in block.items()
        for name in named
    }
    # A finding about the configuration itself has no resource to point at, so
    # it names the top-level block instead — missing_remote_backend reports
    # `terraform`, because the absent backend belongs to that block and to no
    # resource. Those are valid targets, and admitting them keeps this test
    # doing its actual job: catching a recording that drifted from the files.
    declared |= {key for key in merged if not key.startswith("__")}
    for violation in expected["violations"]:
        assert violation["file_path"] in dict(files), (
            f"{case}: violation points at {violation['file_path']!r}, not in the case"
        )
        assert violation["resource_address"] in declared, (
            f"{case}: violation points at {violation['resource_address']!r}, "
            "not declared in the config"
        )


@pytest.mark.parametrize("case", _CASES)
def test_case_scans_to_its_recorded_findings(
    db: Session, terraform_root: TerraformRoot, case: str
) -> None:
    """Each vendored module scans to the finding count and grade recorded for it."""
    expected = _expected(case)
    files, violations = _rooted(case, terraform_root.root_path)

    with _patch_fetch(files), _patch_evaluate(violations):
        result = _run_terraform_scan_impl(str(terraform_root.id))

    assert result["status"] == "done"
    findings = [
        f
        for f in _findings(db, terraform_root)
        if f.resolved_at is None  # noqa: PD011 — SQLModel column value, not pandas
    ]
    assert len(findings) == expected["expected_finding_count"], (
        f"{case}: expected {expected['expected_finding_count']} findings, "
        f"got {sorted(f.resource_address or '' for f in findings)}"
    )
    if expected["expected_grade"] is not None:
        assert result["grade"] == expected["expected_grade"]
    else:
        assert result["grade"] != "A+++"

    # Recorded slugs must be seeded rules, or the scan would silently drop them.
    seeded = {
        r.slug
        for r in db.exec(
            select(Rule).where(Rule.domain == RuleDomain.iac_terraform)
        ).all()
    }
    assert {v["rule_slug"] for v in expected["violations"]} <= seeded


def test_stale_findings_are_resolved_when_a_case_comes_back_clean(
    db: Session, terraform_root: TerraformRoot
) -> None:
    """Rescanning the real corpus with nothing tripped resolves what was open."""
    files, violations = _rooted(_TERRAGOAT, terraform_root.root_path)
    with _patch_fetch(files), _patch_evaluate(violations):
        _run_terraform_scan_impl(str(terraform_root.id))

    with _patch_fetch(files), _patch_evaluate([]):
        _run_terraform_scan_impl(str(terraform_root.id))

    resolved = db.exec(
        select(TerraformFinding)
        .where(TerraformFinding.terraform_root_id == terraform_root.id)
        .where(col(TerraformFinding.resolved_at).is_not(None))
    ).all()
    assert len(resolved) == _expected(_TERRAGOAT)["expected_finding_count"]
    assert all(f.status == FindingStatus.resolved for f in resolved)
