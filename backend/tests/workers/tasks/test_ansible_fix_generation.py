"""Unit tests for the ansible_fix_generation Celery task.

Mirrors the Terraform set case for case, plus the two this engine adds: a
rewrite that drops a Jinja variable and one that drops a ``!vault`` tag both
parse cleanly and must still fail the fix. Those are the cases the shared
"does it still parse?" gate cannot catch, and the reason the ``validate``
contract takes the original content as well as the rewrite.

The before/after pair is the real one from this repository's own deployment:
``roles/docker/tasks/main.yml`` logs in to ECR with an unquoted interpolation,
and the fix is the ``| quote`` filter that ``shell_with_unquoted_variable``
recommends.
"""

import uuid
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, select

from app.models import (
    AnsibleFinding,
    AnsibleFix,
    AnsibleProject,
    AnsibleScan,
    Category,
    FixStatus,
    LLMProvider,
    Organization,
    Repository,
    Rule,
    RuleDomain,
    ScanStatus,
    Severity,
    UserTier,
)
from app.workers.tasks.ansible_fix_generation import run_ansible_fix_generation

_FILE = "roles/docker/tasks/main.yml"

VULNERABLE_YAML = """---
- name: Log in to ECR
  ansible.builtin.shell:
    cmd: >-
      aws ecr get-login-password --region {{ greensecops_region }}
      | docker login --username AWS --password-stdin {{ registry }}
  changed_when: false
  become: true
"""

# The fix the rule asks for: quote both interpolations, change nothing else.
FIXED_YAML = VULNERABLE_YAML.replace(
    "{{ greensecops_region }}", "{{ greensecops_region | quote }}"
).replace("{{ registry }}", "{{ registry | quote }}")

# Parses, classifies as a task file — and silently logs in to the wrong region.
DROPS_VARIABLE_YAML = VULNERABLE_YAML.replace(
    "--region {{ greensecops_region }}", "--region us-east-1"
)

VAULTED_VARS = """---
registry_password: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  6231623764363464
"""
DROPS_TAG_YAML = VAULTED_VARS.replace("!vault |", "|")


@dataclass
class FakeFile:
    path: str
    content: str


@dataclass
class FakeLLMResponse:
    content: str
    prompt_tokens: int = 10
    completion_tokens: int = 20
    run_id: str | None = None


@pytest.fixture()
def repo(db: Session) -> Repository:
    org = Organization(name=f"ansfix-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(org)
    db.commit()
    db.refresh(org)
    repository = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"ansfix/repo-{uuid.uuid4().hex[:8]}",
        installation_id=40001,
        default_branch="main",
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@pytest.fixture()
def project(db: Session, repo: Repository) -> AnsibleProject:
    p = AnsibleProject(repo_id=repo.id, root_path=f"infra/{uuid.uuid4().hex[:8]}")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture()
def scan(db: Session, project: AnsibleProject) -> AnsibleScan:
    s = AnsibleScan(ansible_project_id=project.id, status=ScanStatus.completed)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@pytest.fixture()
def rule(db: Session) -> Rule:
    r = db.exec(select(Rule).where(Rule.domain == RuleDomain.iac_ansible)).first()
    assert r is not None, "No seeded Ansible rules found — init_db may not have run"
    return r


def _finding(
    db: Session,
    project: AnsibleProject,
    scan: AnsibleScan,
    rule: Rule,
    file_path: str = _FILE,
) -> AnsibleFinding:
    f = AnsibleFinding(
        scan_id=scan.id,
        ansible_project_id=project.id,
        rule_id=rule.id,
        file_path=file_path,
        fingerprint=uuid.uuid4().hex[:16],
        severity=Severity.high,
        category=Category.security,
        message="Shell command interpolates a variable without quoting it.",
        task_name="Log in to ECR",
        line_start=2,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


def _pending_fix(
    db: Session, project: AnsibleProject, file_path: str = _FILE
) -> AnsibleFix:
    fix = AnsibleFix(
        ansible_project_id=project.id,
        file_path=file_path,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.pending,
    )
    db.add(fix)
    db.commit()
    db.refresh(fix)
    return fix


def _patch_fetch(files: list[FakeFile]) -> Any:
    return patch(
        "app.workers.tasks.ansible_fix_generation._fetch_ansible_files",
        return_value=files,
    )


def _patch_llm(content: str) -> Any:
    return patch(
        "app.services.file_fix_generation._generate",
        new=AsyncMock(return_value=FakeLLMResponse(content=content)),
    )


def _response(content: str) -> str:
    return f"<full_content>\n{content}</full_content>\n<unfixed>\n</unfixed>"


def test_no_findings_returns_error(db: Session) -> None:
    result = run_ansible_fix_generation([str(uuid.uuid4())])
    assert result["status"] == "error"
    assert result["detail"] == "no_findings_found"


def test_no_pending_fix_is_skipped(
    db: Session, project: AnsibleProject, scan: AnsibleScan, rule: Rule
) -> None:
    finding = _finding(db, project, scan, rule)
    result = run_ansible_fix_generation([str(finding.id)])
    assert result["status"] == "skipped"


def test_success_marks_fix_ready(
    db: Session, project: AnsibleProject, scan: AnsibleScan, rule: Rule
) -> None:
    finding = _finding(db, project, scan, rule)
    fix = _pending_fix(db, project)
    with (
        _patch_fetch([FakeFile(_FILE, VULNERABLE_YAML)]),
        _patch_llm(_response(FIXED_YAML)),
    ):
        result = run_ansible_fix_generation([str(finding.id)])

    assert result["status"] == FixStatus.ready.value
    db.refresh(fix)
    assert fix.status == FixStatus.ready
    assert fix.full_content is not None
    # Both interpolations survive, now quoted — the rule's own recommendation.
    assert "{{ greensecops_region | quote }}" in fix.full_content
    assert "{{ registry | quote }}" in fix.full_content


def test_a_rewrite_that_drops_a_jinja_variable_marks_fix_failed(
    db: Session, project: AnsibleProject, scan: AnsibleScan, rule: Rule
) -> None:
    """The failure the shared parse-only gate cannot see.

    Hardcoding the region parses, classifies as a task file, and would deliver
    cleanly — while pointing the deployment at the wrong AWS region.
    """
    finding = _finding(db, project, scan, rule)
    fix = _pending_fix(db, project)
    with (
        _patch_fetch([FakeFile(_FILE, VULNERABLE_YAML)]),
        _patch_llm(_response(DROPS_VARIABLE_YAML)),
    ):
        result = run_ansible_fix_generation([str(finding.id)])

    assert result["status"] == FixStatus.failed.value
    db.refresh(fix)
    assert fix.status == FixStatus.failed
    assert fix.error_message is not None
    assert "greensecops_region" in fix.error_message
    # Nothing unusable is ever stored, so delivery cannot pick it up later.
    assert fix.full_content is None


def test_a_rewrite_that_drops_a_vault_tag_marks_fix_failed(
    db: Session, project: AnsibleProject, scan: AnsibleScan, rule: Rule
) -> None:
    path = "group_vars/all.yml"
    finding = _finding(db, project, scan, rule, file_path=path)
    fix = _pending_fix(db, project, file_path=path)
    with (
        _patch_fetch([FakeFile(path, VAULTED_VARS)]),
        _patch_llm(_response(DROPS_TAG_YAML)),
    ):
        result = run_ansible_fix_generation([str(finding.id)])

    assert result["status"] == FixStatus.failed.value
    db.refresh(fix)
    assert fix.status == FixStatus.failed
    assert fix.error_message is not None
    assert "!vault" in fix.error_message


def test_invalid_yaml_marks_fix_failed(
    db: Session, project: AnsibleProject, scan: AnsibleScan, rule: Rule
) -> None:
    finding = _finding(db, project, scan, rule)
    fix = _pending_fix(db, project)
    with (
        _patch_fetch([FakeFile(_FILE, VULNERABLE_YAML)]),
        _patch_llm("<full_content>\n- name: [unclosed\n</full_content>"),
    ):
        result = run_ansible_fix_generation([str(finding.id)])

    assert result["status"] == FixStatus.failed.value
    db.refresh(fix)
    assert fix.status == FixStatus.failed
    assert fix.error_message


def test_missing_content_marks_fix_failed(
    db: Session, project: AnsibleProject, scan: AnsibleScan, rule: Rule
) -> None:
    finding = _finding(db, project, scan, rule)
    fix = _pending_fix(db, project)
    with _patch_fetch([FakeFile(_FILE, VULNERABLE_YAML)]), _patch_llm("no block here"):
        result = run_ansible_fix_generation([str(finding.id)])

    assert result["status"] == FixStatus.failed.value
    db.refresh(fix)
    assert fix.status == FixStatus.failed


def test_fetch_failure_marks_fix_failed(
    db: Session, project: AnsibleProject, scan: AnsibleScan, rule: Rule
) -> None:
    finding = _finding(db, project, scan, rule)
    fix = _pending_fix(db, project)
    with patch(
        "app.workers.tasks.ansible_fix_generation._fetch_ansible_files",
        side_effect=RuntimeError("github down"),
    ):
        result = run_ansible_fix_generation([str(finding.id)])

    assert result["status"] == "failed"
    db.refresh(fix)
    assert fix.status == FixStatus.failed


def test_file_missing_from_fetch_marks_fix_failed(
    db: Session, project: AnsibleProject, scan: AnsibleScan, rule: Rule
) -> None:
    finding = _finding(db, project, scan, rule)
    fix = _pending_fix(db, project)
    with _patch_fetch([FakeFile("roles/other/tasks/main.yml", VULNERABLE_YAML)]):
        result = run_ansible_fix_generation([str(finding.id)])

    assert result["status"] == "failed"
    db.refresh(fix)
    assert fix.status == FixStatus.failed
