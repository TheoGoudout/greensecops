"""Unit tests for the installation_sync Celery task (extracted impl function)."""

import uuid
from unittest.mock import MagicMock, patch

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


def _fake_redis_always_acquire() -> MagicMock:
    """Redis mock where every SETNX succeeds (first caller wins)."""
    r = MagicMock()
    r.set.return_value = True
    return r


def test_sync_creates_repositories(db: Session, org: Organization) -> None:
    gh_id1 = int(uuid.uuid4().int % 10**9)
    gh_id2 = int(uuid.uuid4().int % 10**9)
    fake_repos = [
        InstallationRepo(gh_id1, "owner/repo-a", "main"),
        InstallationRepo(gh_id2, "owner/repo-b", "develop"),
    ]
    assert org.installation_id is not None

    mock_redis = _fake_redis_always_acquire()
    with (
        patch(
            "app.workers.tasks.installation_sync._fetch_installation_repositories",
            return_value=fake_repos,
        ),
        patch("redis.Redis.from_url", return_value=mock_redis),
        patch(
            "app.workers.tasks.static_analysis.run_static_analysis.apply_async"
        ) as mock_enqueue,
    ):
        result = _sync_installation_repositories_impl(org.installation_id, str(org.id))

    assert result["status"] == "done"
    assert result["synced"] == 2

    repos = db.exec(select(Repository).where(Repository.org_id == org.id)).all()
    by_id = {r.github_repo_id: r for r in repos}
    assert by_id[gh_id1].full_name == "owner/repo-a"
    assert by_id[gh_id1].default_branch == "main"
    assert by_id[gh_id2].default_branch == "develop"

    # Never-analyzed repos get an initial analysis queued.
    enqueued_repo_ids = {
        call.kwargs["kwargs"]["repo_id"] for call in mock_enqueue.call_args_list
    }
    assert {str(r.id) for r in repos} <= enqueued_repo_ids


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
    mock_redis = _fake_redis_always_acquire()
    with (
        patch(
            "app.workers.tasks.installation_sync._fetch_installation_repositories",
            return_value=fake_repos,
        ),
        patch("redis.Redis.from_url", return_value=mock_redis),
        patch("app.workers.tasks.static_analysis.run_static_analysis.apply_async"),
    ):
        _sync_installation_repositories_impl(org.installation_id, str(org.id))
        # Re-run — should not create duplicates.
        _sync_installation_repositories_impl(org.installation_id, str(org.id))

    repos = db.exec(select(Repository).where(Repository.github_repo_id == gh_id)).all()
    assert len(repos) == 1
    assert repos[0].full_name == "owner/new-name"


def test_sync_deduplicates_analysis_enqueue(db: Session, org: Organization) -> None:
    """When two sync tasks race, each repo gets at most one analysis enqueued."""
    gh_id = int(uuid.uuid4().int % 10**9)
    assert org.installation_id is not None

    fake_repos = [InstallationRepo(gh_id, "owner/repo", "main")]

    # First SETNX succeeds; subsequent calls for the same key return None (already set).
    set_results: dict[str, bool] = {}

    def setnx_side_effect(key: str, value: str, **kwargs: object) -> bool | None:
        if key in set_results:
            return None  # already set
        set_results[key] = True
        return True

    mock_redis = MagicMock()
    mock_redis.set.side_effect = setnx_side_effect

    with (
        patch(
            "app.workers.tasks.installation_sync._fetch_installation_repositories",
            return_value=fake_repos,
        ),
        patch("redis.Redis.from_url", return_value=mock_redis),
        patch(
            "app.workers.tasks.static_analysis.run_static_analysis.apply_async"
        ) as mock_enqueue,
    ):
        # Simulate two concurrent sync tasks for the same installation.
        _sync_installation_repositories_impl(org.installation_id, str(org.id))
        _sync_installation_repositories_impl(org.installation_id, str(org.id))

    # Only one analysis should have been enqueued despite two sync runs.
    assert mock_enqueue.call_count == 1


def test_sync_enqueue_fails_open_on_redis_error(db: Session, org: Organization) -> None:
    """Redis error during dedup check must not block analysis enqueue."""
    gh_id = int(uuid.uuid4().int % 10**9)
    assert org.installation_id is not None

    fake_repos = [InstallationRepo(gh_id, "owner/repo", "main")]
    mock_redis = MagicMock()
    mock_redis.set.side_effect = RuntimeError("redis down")

    with (
        patch(
            "app.workers.tasks.installation_sync._fetch_installation_repositories",
            return_value=fake_repos,
        ),
        patch("redis.Redis.from_url", return_value=mock_redis),
        patch(
            "app.workers.tasks.static_analysis.run_static_analysis.apply_async"
        ) as mock_enqueue,
    ):
        _sync_installation_repositories_impl(org.installation_id, str(org.id))

    mock_enqueue.assert_called_once()


def test_fetch_installation_repositories_uses_app_client() -> None:
    from unittest.mock import AsyncMock

    from app.workers.tasks.installation_sync import _fetch_installation_repositories

    fake_redis = MagicMock()
    fake_redis.aclose = AsyncMock()
    repos = [InstallationRepo(1, "owner/repo", "main")]
    with (
        patch("redis.asyncio.from_url", return_value=fake_redis),
        patch(
            "app.services.github.app_client.GitHubAppClient.list_installation_repositories",
            new=AsyncMock(return_value=repos),
        ),
    ):
        result = _fetch_installation_repositories(42)

    assert result == repos
    fake_redis.aclose.assert_awaited()
