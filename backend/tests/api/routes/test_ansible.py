"""Tests for the /api/v1/ansible endpoints."""

import uuid
from dataclasses import dataclass
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    AnsibleFinding,
    AnsibleProject,
    AnsibleScan,
    Category,
    Organization,
    Repository,
    Rule,
    RuleDomain,
    ScanStatus,
    ScanTrigger,
    Severity,
    UserTier,
)

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


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"ansapi-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
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
        full_name=f"ansapiowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=77777,
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
    assert rule is not None
    return rule


@pytest.fixture()
def completed_scan(db: Session, project: AnsibleProject) -> AnsibleScan:
    scan = AnsibleScan(
        ansible_project_id=project.id,
        status=ScanStatus.completed,
        triggered_by=ScanTrigger.manual,
        score=72.0,
        grade="B",
        file_count=3,
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


# ─── POST /ansible/projects ─────────────────────────────────────────────────


def test_create_project(
    client: TestClient, superuser_token_headers: dict[str, str], repo: Repository
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/ansible/projects",
        headers=superuser_token_headers,
        json={"repo_id": str(repo.id), "root_path": "infra/prod"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["root_path"] == "infra/prod"
    assert body["repo_id"] == str(repo.id)
    assert body["enabled"] is True


def test_create_project_normalizes_slashes(
    client: TestClient, superuser_token_headers: dict[str, str], repo: Repository
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/ansible/projects",
        headers=superuser_token_headers,
        json={"repo_id": str(repo.id), "root_path": "/infra/prod/"},
    )
    assert response.status_code == 201
    assert response.json()["root_path"] == "infra/prod"


def test_an_empty_root_path_means_the_repository_root(
    client: TestClient, superuser_token_headers: dict[str, str], repo: Repository
) -> None:
    # Unlike a Terraform root, an Ansible project frequently *is* the whole
    # repository, with playbooks/ and roles/ at the top level.
    response = client.post(
        f"{settings.API_V1_STR}/ansible/projects",
        headers=superuser_token_headers,
        json={"repo_id": str(repo.id), "root_path": ""},
    )
    assert response.status_code == 201
    assert response.json()["root_path"] == ""


def test_duplicate_project_path_conflicts(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    project: AnsibleProject,
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/ansible/projects",
        headers=superuser_token_headers,
        json={"repo_id": str(repo.id), "root_path": project.root_path},
    )
    assert response.status_code == 409


# ─── GET /ansible/projects ──────────────────────────────────────────────────


def test_list_projects_scoped_to_one_repo(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    project: AnsibleProject,
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/ansible/projects",
        headers=superuser_token_headers,
        params={"repo_id": str(repo.id)},
    )
    assert response.status_code == 200
    assert [p["id"] for p in response.json()] == [str(project.id)]


def test_list_projects_reports_the_latest_grade(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    project: AnsibleProject,
    completed_scan: AnsibleScan,
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/ansible/projects",
        headers=superuser_token_headers,
        params={"repo_id": str(repo.id)},
    )
    body = response.json()[0]
    assert body["latest_grade"] == "B"
    assert body["latest_score"] == 72.0


# ─── PATCH the project, DELETE ───────────────────────────────────────────────


def test_update_project_sets_enabled(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    project: AnsibleProject,
    db: Session,
) -> None:
    response = client.patch(
        f"{settings.API_V1_STR}/ansible/projects/{project.id}",
        headers=superuser_token_headers,
        json={"enabled": False},
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    db.refresh(project)
    assert project.enabled is False


def test_delete_project_cascades_scans(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    project: AnsibleProject,
    completed_scan: AnsibleScan,
    db: Session,
) -> None:
    project_id = project.id
    scan_id = completed_scan.id
    response = client.delete(
        f"{settings.API_V1_STR}/ansible/projects/{project_id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 204
    # A plain select (not db.get()) avoids ObjectDeletedError when refreshing
    # an already-loaded, strongly-referenced identity-map entry for a row
    # another session just deleted.
    assert (
        db.exec(select(AnsibleProject).where(AnsibleProject.id == project_id)).first()
        is None
    )
    assert db.exec(select(AnsibleScan).where(AnsibleScan.id == scan_id)).first() is None


def test_unknown_project_is_not_found(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/ansible/projects/{uuid.uuid4()}/findings",
        headers=superuser_token_headers,
    )
    assert response.status_code == 404
    # The resolver keyed on `project_id` has to answer for *this* engine — a
    # wrong key would surface another engine's message here.
    assert response.json()["detail"] == "Ansible project not found"


# ─── POST /scan ──────────────────────────────────────────────────────────────


def test_trigger_scan_queues_the_task(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    project: AnsibleProject,
) -> None:
    with patch("app.api.routes.ansible.run_ansible_scan.delay") as delayed:
        response = client.post(
            f"{settings.API_V1_STR}/ansible/projects/{project.id}/scans",
            headers=superuser_token_headers,
        )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    delayed.assert_called_once()
    assert delayed.call_args.kwargs["ansible_project_id"] == str(project.id)


def test_scanning_a_disabled_project_is_refused(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    project: AnsibleProject,
    db: Session,
) -> None:
    project.enabled = False
    db.add(project)
    db.commit()
    response = client.post(
        f"{settings.API_V1_STR}/ansible/projects/{project.id}/scans",
        headers=superuser_token_headers,
    )
    assert response.status_code == 403


# ─── GET /scans, /findings ───────────────────────────────────────────────────


def test_list_scans(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    project: AnsibleProject,
    completed_scan: AnsibleScan,
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/ansible/projects/{project.id}/scans",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert [s["id"] for s in body] == [str(completed_scan.id)]
    assert body[0]["file_count"] == 3


def test_list_findings_orders_by_file_then_line(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    project: AnsibleProject,
    completed_scan: AnsibleScan,
    seeded_ansible_rule: Rule,
    db: Session,
) -> None:
    for path, line, name in (
        ("roles/web/tasks/main.yml", 20, "Second"),
        ("playbooks/site.yml", 5, "First"),
        ("roles/web/tasks/main.yml", 4, "Third"),
    ):
        db.add(
            AnsibleFinding(
                scan_id=completed_scan.id,
                ansible_project_id=project.id,
                rule_id=seeded_ansible_rule.id,
                fingerprint=uuid.uuid4().hex[:16],
                severity=Severity.high,
                category=Category.reliability,
                message="m",
                file_path=path,
                line_start=line,
                task_name=name,
            )
        )
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/ansible/projects/{project.id}/findings",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert [(f["file_path"], f["line_start"]) for f in body] == [
        ("playbooks/site.yml", 5),
        ("roles/web/tasks/main.yml", 4),
        ("roles/web/tasks/main.yml", 20),
    ]
    assert body[0]["rule_slug"] == seeded_ansible_rule.slug


def test_resolved_findings_are_hidden_by_default(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    project: AnsibleProject,
    completed_scan: AnsibleScan,
    seeded_ansible_rule: Rule,
    db: Session,
) -> None:
    from datetime import datetime, timezone

    db.add(
        AnsibleFinding(
            scan_id=completed_scan.id,
            ansible_project_id=project.id,
            rule_id=seeded_ansible_rule.id,
            fingerprint=uuid.uuid4().hex[:16],
            severity=Severity.low,
            category=Category.maintainability,
            message="m",
            file_path="playbooks/site.yml",
            resolved_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    hidden = client.get(
        f"{settings.API_V1_STR}/ansible/projects/{project.id}/findings",
        headers=superuser_token_headers,
    )
    assert hidden.json() == []

    shown = client.get(
        f"{settings.API_V1_STR}/ansible/projects/{project.id}/findings",
        headers=superuser_token_headers,
        params={"include_resolved": True},
    )
    assert len(shown.json()) == 1


# ─── GET /files ──────────────────────────────────────────────────────────────


def test_list_files_reports_each_file_s_kind(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    project: AnsibleProject,
) -> None:
    with patch(
        "app.api.routes.ansible._fetch_ansible_files",
        return_value=[FakeAnsibleFile("playbooks/site.yml", _PLAYBOOK)],
    ):
        response = client.get(
            f"{settings.API_V1_STR}/ansible/projects/{project.id}/files",
            headers=superuser_token_headers,
        )
    assert response.status_code == 200
    body = response.json()
    assert body[0]["path"] == "playbooks/site.yml"
    assert body[0]["kind"] == "playbook"
    assert "hosts: web" in body[0]["raw_content"]


def test_list_files_surfaces_a_github_failure_as_502(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    project: AnsibleProject,
) -> None:
    with patch(
        "app.api.routes.ansible._fetch_ansible_files",
        side_effect=RuntimeError("GitHub is down"),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/ansible/projects/{project.id}/files",
            headers=superuser_token_headers,
        )
    assert response.status_code == 502


# ─── Fix generation and delivery ─────────────────────────────────────────────


def _open_finding(
    db: Session,
    project: AnsibleProject,
    completed_scan: AnsibleScan,
    rule: Rule,
    file_path: str,
) -> AnsibleFinding:
    finding = AnsibleFinding(
        scan_id=completed_scan.id,
        ansible_project_id=project.id,
        rule_id=rule.id,
        fingerprint=uuid.uuid4().hex[:16],
        severity=Severity.high,
        category=Category.security,
        message="m",
        file_path=file_path,
        task_name="Log in to ECR",
        line_start=4,
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)
    return finding


def test_generate_fixes_queues_one_task_per_file(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    project: AnsibleProject,
    completed_scan: AnsibleScan,
    seeded_ansible_rule: Rule,
) -> None:
    """Two findings in one file are one rewrite; a third in another is a second.

    The whole file is rewritten in a single LLM call, so grouping by path is
    what keeps the cost proportional to files rather than findings.
    """
    _open_finding(
        db, project, completed_scan, seeded_ansible_rule, "roles/a/tasks/main.yml"
    )
    _open_finding(
        db, project, completed_scan, seeded_ansible_rule, "roles/a/tasks/main.yml"
    )
    _open_finding(
        db, project, completed_scan, seeded_ansible_rule, "playbooks/site.yml"
    )

    with patch("app.api.routes.ansible.run_ansible_fix_generation.delay") as delayed:
        response = client.post(
            f"{settings.API_V1_STR}/ansible/projects/{project.id}/fixes",
            headers=superuser_token_headers,
        )

    assert response.status_code == 202
    assert response.json() == {"status": "queued", "queued": 2}
    assert delayed.call_count == 2


def test_generate_fixes_can_be_narrowed_to_specific_findings(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    project: AnsibleProject,
    completed_scan: AnsibleScan,
    seeded_ansible_rule: Rule,
) -> None:
    wanted = _open_finding(
        db, project, completed_scan, seeded_ansible_rule, "roles/a/tasks/main.yml"
    )
    _open_finding(
        db, project, completed_scan, seeded_ansible_rule, "playbooks/site.yml"
    )

    with patch("app.api.routes.ansible.run_ansible_fix_generation.delay") as delayed:
        response = client.post(
            f"{settings.API_V1_STR}/ansible/projects/{project.id}/fixes",
            headers=superuser_token_headers,
            json={"finding_ids": [str(wanted.id)]},
        )

    assert response.status_code == 202
    assert response.json()["queued"] == 1
    assert delayed.call_args.kwargs["finding_ids"] == [str(wanted.id)]


def test_generate_fixes_with_nothing_open_queues_nothing(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    project: AnsibleProject,
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/ansible/projects/{project.id}/fixes",
        headers=superuser_token_headers,
    )
    assert response.status_code == 202
    assert response.json() == {"status": "no_findings", "queued": 0}


def test_resolved_findings_are_not_regenerated(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    project: AnsibleProject,
    completed_scan: AnsibleScan,
    seeded_ansible_rule: Rule,
) -> None:
    from datetime import datetime, timezone

    finding = _open_finding(
        db, project, completed_scan, seeded_ansible_rule, "roles/a/tasks/main.yml"
    )
    finding.resolved_at = datetime.now(timezone.utc)
    db.add(finding)
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/ansible/projects/{project.id}/fixes",
        headers=superuser_token_headers,
    )
    assert response.json() == {"status": "no_findings", "queued": 0}


def test_list_fixes_returns_the_projects_fixes(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    project: AnsibleProject,
) -> None:
    from app.models import AnsibleFix, FixStatus, LLMProvider

    db.add(
        AnsibleFix(
            ansible_project_id=project.id,
            file_path="roles/a/tasks/main.yml",
            llm_provider=LLMProvider.openai,
            llm_model="gpt-4o-mini",
            status=FixStatus.ready,
            full_content="---\n- name: t\n  ansible.builtin.ping:\n",
        )
    )
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/ansible/projects/{project.id}/fixes",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["file_path"] == "roles/a/tasks/main.yml"
    assert body[0]["status"] == "ready"


def test_deliver_queues_the_task_and_reports_the_branch(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    project: AnsibleProject,
) -> None:
    from app.services.delivery_pr import ansible_fix_branch

    with patch("app.api.routes.ansible.deliver_ansible_fixes.delay") as delayed:
        response = client.post(
            f"{settings.API_V1_STR}/ansible/projects/{project.id}/deliveries",
            headers=superuser_token_headers,
        )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    # The caller gets the branch up front so the UI can link to it before the
    # worker has run.
    assert body["pr_branch"] == ansible_fix_branch(project.id)
    delayed.assert_called_once_with(ansible_project_id=str(project.id), force=False)


def test_fix_endpoints_reject_an_unknown_project(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    unknown = uuid.uuid4()
    for method, suffix in [("post", "fixes"), ("get", "fixes"), ("post", "deliver")]:
        response = getattr(client, method)(
            f"{settings.API_V1_STR}/ansible/projects/{unknown}/{suffix}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 404, (method, suffix)
