"""Unit tests for the installation_sync Celery task (extracted impl function)."""

import uuid
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.models import Organization, Repository, UserTier
from app.services.github.app_client import InstallationRepo
from app.workers.tasks.installation_sync import _sync_installation_repositories_impl


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"sync-org-{uuid.uuid4().hex[:8]}",
        tier=UserTier.free,
        installation_id=int(uuid.uuid4().int % 10**6) + 700000,
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


def test_sync_creates_repositories(db: Session, org: Organization) -> None:
    gh_id1 = int(uuid.uuid4().int % 10**9)
    gh_id2 = int(uuid.uuid4().int % 10**9)
    fake_repos = [
        InstallationRepo(gh_id1, "owner/repo-a", "main"),
        InstallationRepo(gh_id2, "owner/repo-b", "develop"),
    ]
    assert org.installation_id is not None

    with patch(
        "app.workers.tasks.installation_sync._fetch_installation_repositories",
        return_value=fake_repos,
    ):
        result = _sync_installation_repositories_impl(org.installation_id, str(org.id))

    assert result["status"] == "done"
    assert result["synced"] == 2

    repos = db.exec(select(Repository).where(Repository.org_id == org.id)).all()
    by_id = {r.github_repo_id: r for r in repos}
    assert by_id[gh_id1].full_name == "owner/repo-a"
    assert by_id[gh_id1].default_branch == "main"
    assert by_id[gh_id2].default_branch == "develop"
    assert all(r.enabled for r in repos)


def test_sync_is_idempotent_and_reenables(db: Session, org: Organization) -> None:
    gh_id = int(uuid.uuid4().int % 10**9)
    assert org.installation_id is not None

    # Pre-existing disabled repo with a stale name.
    existing = Repository(
        org_id=org.id,
        github_repo_id=gh_id,
        full_name="owner/old-name",
        installation_id=org.installation_id,
        default_branch="main",
        enabled=False,
    )
    db.add(existing)
    db.commit()

    fake_repos = [InstallationRepo(gh_id, "owner/new-name", "main")]
    with patch(
        "app.workers.tasks.installation_sync._fetch_installation_repositories",
        return_value=fake_repos,
    ):
        _sync_installation_repositories_impl(org.installation_id, str(org.id))
        # Re-run — should not create duplicates.
        _sync_installation_repositories_impl(org.installation_id, str(org.id))

    repos = db.exec(select(Repository).where(Repository.github_repo_id == gh_id)).all()
    assert len(repos) == 1
    assert repos[0].full_name == "owner/new-name"
    assert repos[0].enabled is True
