"""Unit tests for the ansible_analysis Celery task (extracted impl function).

What this covers is the persistence half: fingerprint identity across rescans,
the locator columns, stale-finding resolution and scoring. Only OPA is mocked —
the pytest environment ships no ``opa`` binary — so the parse, the envelope
build and the upsert all run for real against a real database.

Parsing fidelity against real-world Ansible lives in
``tests/services/test_ansible_parser.py``, which reads this repository's own
``deploy/ansible/`` tree. The content here is inline so a worker test does not
break when a deployment playbook is edited.
"""

import uuid
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, select

from app.models import (
    AnsibleFinding,
    AnsibleProject,
    AnsibleScan,
    Category,
    FindingStatus,
    Organization,
    Repository,
    Rule,
    RuleDomain,
    ScanFailureKind,
    ScanStatus,
    Severity,
    UserTier,
)
from app.services.opa.evaluator import AnsibleOpaViolation, OpaUnavailableError
from app.workers.tasks.ansible_analysis import (
    AnsibleFetchError,
    _run_ansible_scan_impl,
)

_ROLE_TASKS = """---
- name: Install the Docker Compose plugin
  ansible.builtin.get_url:
    url: https://example.com/docker-compose
    dest: /usr/libexec/docker/cli-plugins/docker-compose
    mode: "0755"
  become: true

- name: Log in to ECR
  ansible.builtin.shell:
    cmd: docker login --password-stdin {{ registry }}
  changed_when: false
  become: true
"""

_PLAYBOOK = """---
- name: Configure the web tier
  hosts: web
  tasks:
    - name: Install nginx
      ansible.builtin.apt:
        name: nginx
        state: present
"""


@dataclass
class FakeAnsibleFile:
    path: str
    content: str
    content_hash: str = ""
    sha: str = ""


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"ans-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
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
        full_name=f"ansowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=40001,
        default_branch="main",
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@pytest.fixture()
def project(db: Session, repo: Repository) -> AnsibleProject:
    proj = AnsibleProject(repo_id=repo.id, root_path=f"infra/{uuid.uuid4().hex[:8]}")
    db.add(proj)
    db.commit()
    db.refresh(proj)
    return proj


@pytest.fixture()
def seeded_ansible_rule(db: Session) -> Rule:
    rule = db.exec(select(Rule).where(Rule.domain == RuleDomain.iac_ansible)).first()
    assert rule is not None, "No seeded Ansible rules found — init_db may not have run"
    return rule


def _patch_fetch(files: list[FakeAnsibleFile]) -> Any:
    return patch(
        "app.workers.tasks.ansible_analysis._fetch_ansible_files",
        return_value=files,
    )


def _patch_evaluate(violations: list[AnsibleOpaViolation]) -> Any:
    return patch(
        "app.workers.tasks.ansible_analysis._evaluate",
        new=AsyncMock(return_value=violations),
    )


def _violation(rule: Rule, **overrides: Any) -> AnsibleOpaViolation:
    fields: dict[str, Any] = {
        "rule_slug": rule.slug,
        "severity": Severity.high.value,
        "category": Category.reliability.value,
        "message": "Task downloads a file with no checksum.",
        "file_path": "roles/docker/tasks/main.yml",
        "task_name": "Install the Docker Compose plugin",
        "line_start": 8,
        "line_end": 16,
        "discriminator": "Install the Docker Compose plugin",
    }
    fields.update(overrides)
    return AnsibleOpaViolation(**fields)


def test_project_not_found_returns_error(db: Session) -> None:
    result = _run_ansible_scan_impl(str(uuid.uuid4()))
    assert result["status"] == "error"
    assert result["detail"] == "ansible_project_not_found"


def test_no_files_returns_no_targets(db: Session, project: AnsibleProject) -> None:
    with _patch_fetch([]):
        result = _run_ansible_scan_impl(str(project.id))

    assert result["status"] == "no_targets"
    scan = db.get(AnsibleScan, uuid.UUID(str(result["scan_id"])))
    assert scan is not None
    assert scan.status == ScanStatus.no_targets


def test_fetch_failure_raises_the_retryable_error(
    db: Session, project: AnsibleProject
) -> None:
    with patch(
        "app.workers.tasks.ansible_analysis._fetch_ansible_files",
        side_effect=RuntimeError("GitHub is down"),
    ):
        with pytest.raises(AnsibleFetchError):
            _run_ansible_scan_impl(str(project.id))


def test_opa_unavailable_marks_the_scan_transiently_failed(
    db: Session, project: AnsibleProject
) -> None:
    files = [FakeAnsibleFile("roles/docker/tasks/main.yml", _ROLE_TASKS)]
    with (
        _patch_fetch(files),
        patch(
            "app.workers.tasks.ansible_analysis._evaluate",
            new=AsyncMock(side_effect=OpaUnavailableError("no opa")),
        ),
    ):
        result = _run_ansible_scan_impl(str(project.id))

    assert result["status"] == "failed"
    scan = db.exec(
        select(AnsibleScan).where(AnsibleScan.ansible_project_id == project.id)
    ).first()
    assert scan is not None
    assert scan.status == ScanStatus.failed
    # Transient, so the maintenance sweeper will retry it rather than give up.
    assert scan.failure_kind == ScanFailureKind.transient


def test_a_violation_is_persisted_with_its_locators(
    db: Session, project: AnsibleProject, seeded_ansible_rule: Rule
) -> None:
    files = [FakeAnsibleFile("roles/docker/tasks/main.yml", _ROLE_TASKS)]
    with _patch_fetch(files), _patch_evaluate([_violation(seeded_ansible_rule)]):
        result = _run_ansible_scan_impl(str(project.id))

    assert result["status"] == "done"
    finding = db.exec(
        select(AnsibleFinding).where(AnsibleFinding.ansible_project_id == project.id)
    ).first()
    assert finding is not None
    assert finding.file_path == "roles/docker/tasks/main.yml"
    assert finding.task_name == "Install the Docker Compose plugin"
    assert finding.line_start == 8
    assert finding.status == FindingStatus.open


def test_rescanning_the_same_violation_reuses_one_finding(
    db: Session, project: AnsibleProject, seeded_ansible_rule: Rule
) -> None:
    files = [FakeAnsibleFile("roles/docker/tasks/main.yml", _ROLE_TASKS)]
    for _ in range(2):
        with _patch_fetch(files), _patch_evaluate([_violation(seeded_ansible_rule)]):
            _run_ansible_scan_impl(str(project.id))

    findings = db.exec(
        select(AnsibleFinding).where(AnsibleFinding.ansible_project_id == project.id)
    ).all()
    # The fingerprint keys on (project, rule, file, task name), none of which
    # moved, so the second scan updates the first finding rather than adding one.
    assert len(findings) == 1


def test_two_tasks_in_one_file_are_two_findings(
    db: Session, project: AnsibleProject, seeded_ansible_rule: Rule
) -> None:
    files = [FakeAnsibleFile("roles/docker/tasks/main.yml", _ROLE_TASKS)]
    violations = [
        _violation(seeded_ansible_rule),
        _violation(
            seeded_ansible_rule,
            task_name="Log in to ECR",
            discriminator="Log in to ECR",
            line_start=47,
        ),
    ]
    with _patch_fetch(files), _patch_evaluate(violations):
        _run_ansible_scan_impl(str(project.id))

    findings = db.exec(
        select(AnsibleFinding).where(AnsibleFinding.ansible_project_id == project.id)
    ).all()
    assert len(findings) == 2
    assert {f.task_name for f in findings} == {
        "Install the Docker Compose plugin",
        "Log in to ECR",
    }


def test_a_violation_that_stops_firing_is_resolved(
    db: Session, project: AnsibleProject, seeded_ansible_rule: Rule
) -> None:
    files = [FakeAnsibleFile("roles/docker/tasks/main.yml", _ROLE_TASKS)]
    with _patch_fetch(files), _patch_evaluate([_violation(seeded_ansible_rule)]):
        _run_ansible_scan_impl(str(project.id))
    with _patch_fetch(files), _patch_evaluate([]):
        _run_ansible_scan_impl(str(project.id))

    finding = db.exec(
        select(AnsibleFinding).where(AnsibleFinding.ansible_project_id == project.id)
    ).first()
    assert finding is not None
    assert finding.status == FindingStatus.resolved


def test_a_clean_project_scores_full_marks(
    db: Session, project: AnsibleProject
) -> None:
    files = [
        FakeAnsibleFile("playbooks/deploy.yml", _PLAYBOOK),
        FakeAnsibleFile("roles/docker/tasks/main.yml", _ROLE_TASKS),
    ]
    with _patch_fetch(files), _patch_evaluate([]):
        result = _run_ansible_scan_impl(str(project.id))

    assert result["status"] == "done"
    scan = db.exec(
        select(AnsibleScan).where(AnsibleScan.ansible_project_id == project.id)
    ).first()
    assert scan is not None
    assert scan.score == 100.0
    assert scan.grade == "A+++"
    # Ansible scores per file, so the scan records how many it saw.
    assert scan.file_count == 2
