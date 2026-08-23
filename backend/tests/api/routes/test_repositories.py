"""Tests for the /api/v1/repositories/ endpoints."""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.routes.repositories import _inject_action_into_workflow
from app.core.config import settings
from app.models import (
    Analysis,
    Organization,
    OrgMember,
    OrgRole,
    Repository,
    ScanStatus,
    ScanTrigger,
    User,
    UserTier,
    WorkflowFile,
)
from tests.utils.user import authentication_token_from_email, create_random_user

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"repos-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
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
        full_name=f"repoowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=11111,
        enabled=True,
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


# ─── GET /repositories/ ──────────────────────────────────────────────────────


def test_list_repositories_empty(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    # Arrange — create a fresh org with no repos
    fresh_org = Organization(
        name=f"empty-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(fresh_org)
    db.commit()
    db.refresh(fresh_org)

    # Act
    response = client.get(
        f"{settings.API_V1_STR}/repositories/",
        params={"org_id": str(fresh_org.id)},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 0


def test_list_repositories_with_data(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    org: Organization,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/repositories/",
        params={"org_id": str(org.id)},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    ids = [r["id"] for r in data]
    assert str(repo.id) in ids


def test_list_repositories_filter_by_enabled(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    org: Organization,
) -> None:
    # Arrange — create one enabled and one disabled repo
    enabled_repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/enabled-{uuid.uuid4().hex[:8]}",
        installation_id=22222,
        enabled=True,
    )
    disabled_repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/disabled-{uuid.uuid4().hex[:8]}",
        installation_id=33333,
        enabled=False,
    )
    db.add(enabled_repo)
    db.add(disabled_repo)
    db.commit()
    db.refresh(enabled_repo)
    db.refresh(disabled_repo)

    # Act — only enabled
    response = client.get(
        f"{settings.API_V1_STR}/repositories/",
        params={"org_id": str(org.id), "enabled": "true"},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    returned_ids = {r["id"] for r in data}
    assert str(enabled_repo.id) in returned_ids
    assert str(disabled_repo.id) not in returned_ids


# ─── GET /repositories/{id} ───────────────────────────────────────────────────


def test_get_repository_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/repositories/{repo.id}",
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(repo.id)
    assert body["full_name"] == repo.full_name


def test_get_repository_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/repositories/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Repository not found"


# ─── PATCH /repositories/{id}/toggle ─────────────────────────────────────────


def test_toggle_repository_enable(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    org: Organization,
) -> None:
    # Arrange — create a disabled repo
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/toggle-{uuid.uuid4().hex[:8]}",
        installation_id=44444,
        enabled=False,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    # Act
    response = client.patch(
        f"{settings.API_V1_STR}/repositories/{repo.id}/toggle",
        params={"enabled": "true"},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["repo_id"] == str(repo.id)

    db.refresh(repo)
    assert repo.enabled is True


def test_toggle_repository_disable(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    db: Session,
) -> None:
    # Act
    response = client.patch(
        f"{settings.API_V1_STR}/repositories/{repo.id}/toggle",
        params={"enabled": "false"},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False

    db.refresh(repo)
    assert repo.enabled is False


def test_toggle_repository_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    # Act
    response = client.patch(
        f"{settings.API_V1_STR}/repositories/{uuid.uuid4()}/toggle",
        params={"enabled": "true"},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Repository not found"


def test_toggle_repository_enable_blocks_over_repo_quota(
    client: TestClient,
    db: Session,
    org: Organization,
) -> None:
    """Enabling a repo beyond the tier's repo cap is rejected."""
    user = create_random_user(db)
    db.add(OrgMember(org_id=org.id, user_id=user.id, role=OrgRole.owner))
    db.commit()
    headers = authentication_token_from_email(client=client, email=user.email, db=db)

    free_repo_limit = 3
    for n in range(free_repo_limit):
        db.add(
            Repository(
                org_id=org.id,
                github_repo_id=int(uuid.uuid4().int % 10**9),
                full_name=f"owner/enabled-{n}-{uuid.uuid4().hex[:8]}",
                installation_id=55555,
                enabled=True,
            )
        )
    extra_repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/extra-{uuid.uuid4().hex[:8]}",
        installation_id=55555,
        enabled=False,
    )
    db.add(extra_repo)
    db.commit()
    db.refresh(extra_repo)

    # Act — enabling a 4th repo exceeds the free tier's cap of 3
    response = client.patch(
        f"{settings.API_V1_STR}/repositories/{extra_repo.id}/toggle",
        params={"enabled": "true"},
        headers=headers,
    )

    # Assert
    assert response.status_code == 402
    # The 402 detail is a structured payload now, not a bare string: it
    # names the meter, the cap and what to do next so the UI can render an
    # upgrade button rather than pattern-matching prose.
    detail = response.json()["detail"]
    assert detail["code"] == "quota_exceeded"
    assert detail["meter"] == "repos"
    assert "repositories" in detail["message"]
    db.refresh(extra_repo)
    assert extra_repo.enabled is False


def test_toggle_repository_disable_never_blocked_by_quota(
    client: TestClient,
    db: Session,
    org: Organization,
) -> None:
    """Disabling a repo is never quota-gated, even already over the cap."""
    user = create_random_user(db)
    db.add(OrgMember(org_id=org.id, user_id=user.id, role=OrgRole.owner))
    db.commit()
    headers = authentication_token_from_email(client=client, email=user.email, db=db)

    over_cap_repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/over-cap-{uuid.uuid4().hex[:8]}",
        installation_id=55555,
        enabled=True,
    )
    db.add(over_cap_repo)
    db.commit()
    db.refresh(over_cap_repo)

    response = client.patch(
        f"{settings.API_V1_STR}/repositories/{over_cap_repo.id}/toggle",
        params={"enabled": "false"},
        headers=headers,
    )

    assert response.status_code == 200
    db.refresh(over_cap_repo)
    assert over_cap_repo.enabled is False


# ─── Auto-fix tier gate ──────────────────────────────────────────────────────


def _auto_fix_repo(db: Session, org: Organization) -> Repository:
    repository = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/autofix-{uuid.uuid4().hex[:8]}",
        installation_id=55555,
        enabled=True,
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


def test_toggle_auto_fix_blocked_on_free_tier(
    client: TestClient,
    db: Session,
    org: Organization,
) -> None:
    """A free-tier owner cannot enable auto-fix (paid feature)."""
    user = create_random_user(db)
    user.tier = UserTier.free
    db.add(user)
    db.add(OrgMember(org_id=org.id, user_id=user.id, role=OrgRole.owner))
    db.commit()
    headers = authentication_token_from_email(client=client, email=user.email, db=db)
    repo = _auto_fix_repo(db, org)

    response = client.patch(
        f"{settings.API_V1_STR}/repositories/{repo.id}/auto-fix",
        params={"enabled": "true"},
        headers=headers,
    )

    assert response.status_code == 402
    detail = response.json()["detail"]
    assert detail["code"] == "feature_not_in_plan"
    # Names the plan that unlocks it, not just "upgrade".
    assert "Starter" in detail["message"]
    db.refresh(repo)
    assert repo.auto_fix_enabled is False


def test_toggle_auto_fix_allowed_on_paid_tier(
    client: TestClient,
    db: Session,
    org: Organization,
) -> None:
    """A starter-tier owner can enable auto-fix."""
    user = create_random_user(db)
    user.tier = UserTier.starter
    db.add(user)
    db.add(OrgMember(org_id=org.id, user_id=user.id, role=OrgRole.owner))
    db.commit()
    headers = authentication_token_from_email(client=client, email=user.email, db=db)
    repo = _auto_fix_repo(db, org)

    response = client.patch(
        f"{settings.API_V1_STR}/repositories/{repo.id}/auto-fix",
        params={"enabled": "true"},
        headers=headers,
    )

    assert response.status_code == 200
    db.refresh(repo)
    assert repo.auto_fix_enabled is True


def test_toggle_auto_fix_superuser_bypasses_gate(
    client: TestClient,
    db: Session,
    org: Organization,
    superuser_token_headers: dict[str, str],
) -> None:
    """A superuser can force-enable auto-fix on a free-tier org's repo (OSS)."""
    owner = create_random_user(db)
    owner.tier = UserTier.free
    db.add(owner)
    db.add(OrgMember(org_id=org.id, user_id=owner.id, role=OrgRole.owner))
    db.commit()
    repo = _auto_fix_repo(db, org)

    response = client.patch(
        f"{settings.API_V1_STR}/repositories/{repo.id}/auto-fix",
        params={"enabled": "true"},
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    db.refresh(repo)
    assert repo.auto_fix_enabled is True


def test_toggle_auto_fix_disable_never_blocked(
    client: TestClient,
    db: Session,
    org: Organization,
) -> None:
    """Disabling auto-fix is always allowed, even for a free-tier owner."""
    user = create_random_user(db)
    user.tier = UserTier.free
    db.add(user)
    db.add(OrgMember(org_id=org.id, user_id=user.id, role=OrgRole.owner))
    db.commit()
    headers = authentication_token_from_email(client=client, email=user.email, db=db)
    repo = _auto_fix_repo(db, org)
    repo.auto_fix_enabled = True
    db.add(repo)
    db.commit()

    response = client.patch(
        f"{settings.API_V1_STR}/repositories/{repo.id}/auto-fix",
        params={"enabled": "false"},
        headers=headers,
    )

    assert response.status_code == 200
    db.refresh(repo)
    assert repo.auto_fix_enabled is False


# ─── Org-scoped access for non-superusers ────────────────────────────────────


def _make_org_with_repo(db: Session, suffix: str) -> tuple[Organization, Repository]:
    organization = Organization(name=f"scope-{suffix}-{uuid.uuid4().hex[:6]}")
    db.add(organization)
    db.commit()
    db.refresh(organization)
    repository = Repository(
        org_id=organization.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/scope-{suffix}-{uuid.uuid4().hex[:6]}",
        installation_id=int(uuid.uuid4().int % 10**6),
        enabled=True,
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return organization, repository


def test_list_repositories_scoped_to_user_orgs(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None

    my_org, my_repo = _make_org_with_repo(db, "mine")
    _other_org, other_repo = _make_org_with_repo(db, "theirs")
    db.add(OrgMember(org_id=my_org.id, user_id=user.id, role=OrgRole.owner))
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/repositories/", headers=normal_user_token_headers
    )

    assert response.status_code == 200
    ids = {r["id"] for r in response.json()}
    assert str(my_repo.id) in ids
    assert str(other_repo.id) not in ids


def test_get_repository_cross_org_returns_404(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    _other_org, other_repo = _make_org_with_repo(db, "getforbidden")

    response = client.get(
        f"{settings.API_V1_STR}/repositories/{other_repo.id}",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Repository not found"


def test_toggle_repository_cross_org_returns_404(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    _other_org, other_repo = _make_org_with_repo(db, "toggleforbidden")

    response = client.patch(
        f"{settings.API_V1_STR}/repositories/{other_repo.id}/toggle",
        params={"enabled": "false"},
        headers=normal_user_token_headers,
    )

    assert response.status_code == 404
    db.refresh(other_repo)
    assert other_repo.enabled is True


# ─── Grade fields on list / get endpoints ─────────────────────────────────────


def _make_workflow_file(
    db: Session, repo: Repository, path: str = ".github/workflows/ci.yml"
) -> WorkflowFile:
    wf = WorkflowFile(
        repo_id=repo.id,
        path=path,
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs: {}",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


def _make_completed_analysis(
    db: Session, repo: Repository, wf: WorkflowFile, score: float, grade: str
) -> Analysis:
    a = Analysis(
        repo_id=repo.id,
        workflow_file_id=wf.id,
        content_hash=wf.content_hash,
        status=ScanStatus.completed,
        score=score,
        grade=grade,
        triggered_by=ScanTrigger.manual,
        branch="main",
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def test_list_repositories_grade_null_without_analyses(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    org: Organization,
) -> None:
    # Arrange — repo exists but has no completed analyses
    response = client.get(
        f"{settings.API_V1_STR}/repositories/",
        params={"org_id": str(org.id)},
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    repo_data = next(r for r in data if r["id"] == str(repo.id))
    assert repo_data["avg_score"] is None
    assert repo_data["grade"] == "-"


def test_list_repositories_grade_populated(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    org: Organization,
) -> None:
    # Arrange — two workflow files with scores 80 and 60 → avg 70 → grade B
    wf1 = _make_workflow_file(db, repo, ".github/workflows/ci.yml")
    wf2 = _make_workflow_file(db, repo, ".github/workflows/deploy.yml")
    _make_completed_analysis(db, repo, wf1, score=80.0, grade="B")
    _make_completed_analysis(db, repo, wf2, score=60.0, grade="C")

    response = client.get(
        f"{settings.API_V1_STR}/repositories/",
        params={"org_id": str(org.id)},
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    repo_data = next(r for r in data if r["id"] == str(repo.id))
    assert repo_data["avg_score"] == 70.0
    assert repo_data["grade"] == "B"


def test_get_repository_grade_populated(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
) -> None:
    # Arrange — one workflow file with score 92 → grade A+
    wf = _make_workflow_file(db, repo)
    _make_completed_analysis(db, repo, wf, score=92.0, grade="A+")

    response = client.get(
        f"{settings.API_V1_STR}/repositories/{repo.id}",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["avg_score"] == 92.0
    assert body["grade"] == "A+"


# ─── GET /repositories/external ─────────────────────────────────────────────


def test_list_external_repositories_empty(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/repositories/external",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_list_external_repositories_returns_external_only(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    org: Organization,
) -> None:
    # "!" sorts before any real repo name: the endpoint pages by full_name
    # (default limit 50), so this keeps the row on page one even when other
    # tests have left repositories behind in the database.
    ext_repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"!ext-owner/ext-{uuid.uuid4().hex[:8]}",
        installation_id=None,
        enabled=True,
        is_external=True,
    )
    normal_repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"normal-owner/normal-{uuid.uuid4().hex[:8]}",
        installation_id=55555,
        enabled=True,
        is_external=False,
    )
    db.add(ext_repo)
    db.add(normal_repo)
    db.commit()
    db.refresh(ext_repo)
    db.refresh(normal_repo)

    response = client.get(
        f"{settings.API_V1_STR}/repositories/external",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    ids = {r["id"] for r in response.json()}
    assert str(ext_repo.id) in ids
    assert str(normal_repo.id) not in ids


# ─── GET /repositories/{id}/workflow-files ───────────────────────────────────


def test_list_workflow_files_empty(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
) -> None:
    # Arrange — repo has no workflow files
    response = client.get(
        f"{settings.API_V1_STR}/repositories/{repo.id}/workflow-files",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.json() == []


def test_list_workflow_files_returns_files(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
) -> None:
    # Arrange — add a workflow file to the repo
    wf = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/ci.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs: {}",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)

    response = client.get(
        f"{settings.API_V1_STR}/repositories/{repo.id}/workflow-files",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    paths = [f["path"] for f in data]
    assert ".github/workflows/ci.yml" in paths


def test_list_workflow_files_excludes_soft_deleted(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
) -> None:
    # Arrange — one present file and one soft-deleted (removed from the repo).
    present = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/ci.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs: {}",
    )
    deleted = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/gone.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs: {}",
        deleted_at=datetime.now(timezone.utc),
    )
    db.add(present)
    db.add(deleted)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/repositories/{repo.id}/workflow-files",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    paths = [f["path"] for f in response.json()]
    assert ".github/workflows/ci.yml" in paths
    assert ".github/workflows/gone.yml" not in paths


def test_grade_excludes_soft_deleted_workflow_file(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
) -> None:
    # Arrange — a present file scored 80 and a deleted file scored 40. The
    # deleted file's stale analysis must not drag the grade down.
    present = _make_workflow_file(db, repo, ".github/workflows/ci.yml")
    deleted = _make_workflow_file(db, repo, ".github/workflows/gone.yml")
    _make_completed_analysis(db, repo, present, score=80.0, grade="B")
    _make_completed_analysis(db, repo, deleted, score=40.0, grade="F")
    deleted.deleted_at = datetime.now(timezone.utc)
    db.add(deleted)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/repositories/{repo.id}",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    # Only the present file's score counts → avg 80, not (80+40)/2 = 60.
    assert response.json()["avg_score"] == 80.0


def test_list_workflow_files_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/repositories/{uuid.uuid4()}/workflow-files",
        headers=superuser_token_headers,
    )

    assert response.status_code == 404


# ─── _inject_action_into_workflow ───────────────────────────────────────────

_WORKFLOW_NO_ACTION = (
    "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
    "    steps:\n      - uses: actions/checkout@v4\n"
)


def test_inject_action_uses_default_ref_when_omitted() -> None:
    new_content, modified = _inject_action_into_workflow(_WORKFLOW_NO_ACTION)
    assert modified is True
    assert f"uses: {settings.GITHUB_ACTION_REF}\n" in new_content


def test_inject_action_uses_pinned_ref_when_provided() -> None:
    pinned_ref = "greensecops/greensecops-action@" + "a" * 40 + " # v1"
    new_content, modified = _inject_action_into_workflow(
        _WORKFLOW_NO_ACTION, action_ref=pinned_ref
    )
    assert modified is True
    assert f"uses: {pinned_ref}\n" in new_content


def test_inject_action_already_present_detected_with_pinned_ref() -> None:
    # "already present" detection compares by owner/repo prefix, so a
    # previously-injected pinned step is still recognized on a second pass.
    # (permissions already set too, else that insertion alone would report modified.)
    pinned_ref = "greensecops/greensecops-action@" + "a" * 40 + " # v1"
    already_injected = (
        "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
        "    permissions:\n      id-token: write\n"
        f"    steps:\n      - uses: {pinned_ref}\n"
    )
    _new_content, modified = _inject_action_into_workflow(
        already_injected, action_ref=pinned_ref
    )
    assert modified is False


# ─── POST /repositories/{id}/integrate-action ───────────────────────────────


def test_integrate_action_no_workflow_files(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/repositories/{repo.id}/integrate-action",
        headers=superuser_token_headers,
    )
    assert response.status_code == 404
    assert "No workflow files" in response.json()["detail"]


def test_integrate_action_no_installation(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    org: Organization,
) -> None:
    repo_no_install = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/no-install-{uuid.uuid4().hex[:8]}",
        installation_id=None,
        enabled=True,
    )
    db.add(repo_no_install)
    db.commit()
    db.refresh(repo_no_install)
    wf = WorkflowFile(
        repo_id=repo_no_install.id,
        path=".github/workflows/ci.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n",
    )
    db.add(wf)
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/repositories/{repo_no_install.id}/integrate-action",
        headers=superuser_token_headers,
    )
    assert response.status_code == 400
    assert "no GitHub App installation" in response.json()["detail"]


def test_integrate_action_already_present(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    org: Organization,
) -> None:
    from unittest.mock import AsyncMock

    repo_with_install = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/already-int-{uuid.uuid4().hex[:8]}",
        installation_id=99999,
        enabled=True,
    )
    db.add(repo_with_install)
    db.commit()
    db.refresh(repo_with_install)
    wf = WorkflowFile(
        repo_id=repo_with_install.id,
        path=".github/workflows/ci.yml",
        content_hash=uuid.uuid4().hex,
        raw_content=(
            "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
            "    permissions:\n      id-token: write\n    steps:\n"
            f"      - uses: {settings.GITHUB_ACTION_REF}\n"
        ),
    )
    db.add(wf)
    db.commit()

    mock_client = AsyncMock()
    mock_client.get_installation_token = AsyncMock(return_value="tok")

    from unittest.mock import MagicMock, patch

    from github.GithubException import GithubException

    from app.api.deps import get_github_app_client
    from app.main import app as fastapi_app

    # Live-content and README fetches 404, so the route falls back to the
    # stored raw_content (already integrated) and skips badge injection.
    gh_repo = MagicMock()
    gh_repo.get_contents.side_effect = GithubException(404, "Not Found", None)
    gh_repo.get_readme.side_effect = GithubException(404, "Not Found", None)
    gh_instance = MagicMock()
    gh_instance.get_repo.return_value = gh_repo

    fastapi_app.dependency_overrides[get_github_app_client] = lambda: mock_client
    try:
        with (
            patch("github.Github", return_value=gh_instance),
            patch(
                "app.services.github.sha_resolver.resolve_pinned_ref",
                AsyncMock(return_value=settings.GITHUB_ACTION_REF),
            ),
        ):
            response = client.post(
                f"{settings.API_V1_STR}/repositories/{repo_with_install.id}/integrate-action",
                headers=superuser_token_headers,
            )
    finally:
        fastapi_app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "already present" in response.json()["detail"]


def test_integrate_action_badge_url_prefers_greensecops_public_url(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    org: Organization,
) -> None:
    """The badge URL embedded in the README uses GREENSECOPS_PUBLIC_URL (the
    dev tunnel base) when it's set, instead of always falling back to
    BACKEND_HOST — otherwise a badge added during local dev points at
    localhost, which GitHub can't reach."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from github.GithubException import GithubException

    from app.api.deps import get_github_app_client
    from app.main import app as fastapi_app
    from app.services.github.fix_delivery import FixDeliveryResult

    repo_with_install = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/badge-url-{uuid.uuid4().hex[:8]}",
        installation_id=99999,
        enabled=True,
    )
    db.add(repo_with_install)
    db.commit()
    db.refresh(repo_with_install)
    wf = WorkflowFile(
        repo_id=repo_with_install.id,
        path=".github/workflows/ci.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs:\n  build:\n    steps:\n      - run: echo hi\n",
    )
    db.add(wf)
    db.commit()

    mock_client = AsyncMock()
    mock_client.get_installation_token = AsyncMock(return_value="tok")

    gh_readme = MagicMock()
    gh_readme.decoded_content = b"# owner/repo\n\nSome description.\n"
    gh_readme.path = "README.md"
    gh_repo = MagicMock()
    gh_repo.get_contents.side_effect = GithubException(404, "Not Found", None)
    gh_repo.get_readme.return_value = gh_readme
    gh_instance = MagicMock()
    gh_instance.get_repo.return_value = gh_repo

    mock_deliver = AsyncMock(
        return_value=FixDeliveryResult(pr_url="https://github.com/o/r/pull/1")
    )

    fastapi_app.dependency_overrides[get_github_app_client] = lambda: mock_client
    try:
        with (
            patch("github.Github", return_value=gh_instance),
            patch(
                "app.api.routes.repositories._inject_badge_via_llm",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.services.github.fix_delivery.FixDeliveryService"
                ".update_or_create_workflow_action_pr",
                mock_deliver,
            ),
            patch.object(settings, "GREENSECOPS_PUBLIC_URL", "https://tunnel.ngrok.io"),
            patch(
                "app.services.github.sha_resolver.resolve_pinned_ref",
                AsyncMock(return_value=settings.GITHUB_ACTION_REF),
            ),
        ):
            response = client.post(
                f"{settings.API_V1_STR}/repositories/{repo_with_install.id}/integrate-action",
                headers=superuser_token_headers,
            )
    finally:
        fastapi_app.dependency_overrides.clear()

    assert response.status_code == 202
    assert mock_deliver.await_count == 1
    file_changes = mock_deliver.await_args.kwargs["file_changes"]
    readme_content = dict(file_changes)["README.md"]
    owner, name = repo_with_install.full_name.split("/", 1)
    assert (
        f"https://tunnel.ngrok.io{settings.API_V1_STR}/badges/{owner}/{name}/"
        in readme_content
    )
    assert "localhost:8000" not in readme_content


# ─── auto-fix toggle and branches listing ────────────────────────────────────


def test_toggle_auto_fix_enable(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    db: Session,
) -> None:
    response = client.patch(
        f"{settings.API_V1_STR}/repositories/{repo.id}/auto-fix",
        params={"enabled": "true"},
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["auto_fix_enabled"] is True
    assert body["repo_id"] == str(repo.id)

    db.refresh(repo)
    assert repo.auto_fix_enabled is True


def test_toggle_auto_fix_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    response = client.patch(
        f"{settings.API_V1_STR}/repositories/{uuid.uuid4()}/auto-fix",
        params={"enabled": "true"},
        headers=superuser_token_headers,
    )

    assert response.status_code == 404


def test_list_repository_branches(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    db: Session,
) -> None:
    from app.models import Analysis, ScanStatus, WorkflowFile

    wf = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/branches.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\n",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    for branch, status in [
        ("main", ScanStatus.completed),
        ("dev", ScanStatus.completed),
        ("main", ScanStatus.completed),
        ("wip", ScanStatus.running),
    ]:
        db.add(
            Analysis(
                repo_id=repo.id,
                workflow_file_id=wf.id,
                content_hash=uuid.uuid4().hex,
                status=status,
                branch=branch,
            )
        )
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/repositories/{repo.id}/branches",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.json() == ["dev", "main"]


# ─── Branch scoping ───────────────────────────────────────────────────────────


def test_grade_ignores_feature_branch_analyses(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
) -> None:
    main_wf = _make_workflow_file(db, repo)
    _make_completed_analysis(db, repo, main_wf, score=90.0, grade="A")

    feature_wf = WorkflowFile(
        repo_id=repo.id,
        branch="feature",
        path=".github/workflows/ci.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs: {}",
    )
    db.add(feature_wf)
    db.commit()
    db.refresh(feature_wf)
    bad = Analysis(
        repo_id=repo.id,
        workflow_file_id=feature_wf.id,
        content_hash=feature_wf.content_hash,
        status=ScanStatus.completed,
        score=10.0,
        grade="F",
        triggered_by=ScanTrigger.manual,
        branch="feature",
    )
    db.add(bad)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/repositories/{repo.id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    # Only the default-branch analysis counts (not the feature-branch F).
    assert body["avg_score"] == 90.0


def test_list_workflow_files_scoped_to_branch(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
) -> None:
    _make_workflow_file(db, repo, path=".github/workflows/main-only.yml")
    feature_wf = WorkflowFile(
        repo_id=repo.id,
        branch="feature",
        path=".github/workflows/feature-only.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs: {}",
    )
    db.add(feature_wf)
    db.commit()

    url = f"{settings.API_V1_STR}/repositories/{repo.id}/workflow-files"
    default_listing = client.get(url, headers=superuser_token_headers)
    assert default_listing.status_code == 200
    paths = [wf["path"] for wf in default_listing.json()]
    assert paths == [".github/workflows/main-only.yml"]

    feature_listing = client.get(
        url, params={"branch": "feature"}, headers=superuser_token_headers
    )
    assert feature_listing.status_code == 200
    feature_paths = [wf["path"] for wf in feature_listing.json()]
    assert feature_paths == [".github/workflows/feature-only.yml"]
    assert feature_listing.json()[0]["branch"] == "feature"
