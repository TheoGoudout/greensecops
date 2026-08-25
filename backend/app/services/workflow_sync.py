"""Reconcile a repository's stored workflow files with what is on GitHub.

This module owns ``WorkflowFile`` state. Nothing else writes those rows.

That sentence is the whole point of the module existing. Storing workflow files
used to be a *by-product* of running an analysis: the upsert lived inside the
per-file loop in ``workers.tasks.static_analysis``, below the content-dedup
check. Any file the dedup skipped therefore kept whatever content it had last
been analysed with — so content going ``A → B → A`` left the row frozen on
``B``, and a newly added file whose content matched some already-analysed file
on the same branch got no row at all (dedup keys on
``(content_hash, repo_id, branch)``, not on path). Everything downstream — the
workflow list in the UI, the base a fix is generated from, the freshness check
that guards delivery — then read a snapshot that did not match the repository.

Two properties keep it honest:

**Every read is pinned to a resolved commit.** The ref is resolved to a head SHA
first, and the content fetched at that immutable SHA. A branch name is a moving
target, and — more importantly — a fetch against a ref that no longer exists
404s exactly like a repository with no ``.github/workflows`` directory does.
Without a separate resolve step those two are indistinguishable, and reading the
second as the first soft-deletes every workflow file the branch has.

**A write never goes backwards.** ``WorkflowFile.fetched_at`` records when the
sync that wrote the row resolved its ref, and a sync whose own resolve is older
than that leaves the row alone. Analyses are serialised per repo by a Redis
lock, but a lock orders nothing: a task delayed by lock contention or a fetch
retry can run after a newer one, and used to overwrite fresh content with the
commit its webhook happened to carry. Git SHAs have no order to compare; server
timestamps do.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import (
    Issue,
    IssueResolutionReason,
    Repository,
    WorkflowFile,
)
from app.services import state_machines as sm
from app.services.deduplication import compute_content_hash

if TYPE_CHECKING:
    from app.services.github.app_client import WorkflowFileContent

logger = logging.getLogger(__name__)


class WorkflowFetchError(Exception):
    """Raised when workflow files cannot be fetched from GitHub (transient)."""


@dataclass(frozen=True)
class WorkflowSyncResult:
    """What one sync saw and what it changed.

    ``contents`` and ``rows`` are the analysis inputs — the content read at
    ``head_sha`` and the row it was stored on, keyed by path. Callers analyse
    from ``contents``, never from ``WorkflowFile.raw_content``, so that a row
    whose write lost the ordering race cannot feed a newer analysis older text.
    """

    branch: str
    head_sha: str | None
    resolved_at: datetime
    contents: dict[str, str] = field(default_factory=dict)
    rows: dict[str, WorkflowFile] = field(default_factory=dict)
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    restored: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    skipped_stale: list[str] = field(default_factory=list)
    # True when the ref could not be resolved and the fetch came back empty, so
    # "no workflows" and "branch is gone" are indistinguishable. Reconciliation
    # is suppressed and the caller should not treat the empty listing as fact.
    ref_unresolved: bool = False

    @property
    def counts(self) -> dict[str, int]:
        """The shape the API returns; also what the log line reports."""
        return {
            "added": len(self.added),
            "updated": len(self.updated),
            "unchanged": len(self.unchanged),
            "restored": len(self.restored),
            "deleted": len(self.deleted),
            "skipped_stale": len(self.skipped_stale),
        }


def fetch_workflow_files_for_repo(
    repo: Repository, ref: str | None = None
) -> list[WorkflowFileContent]:
    """Synchronous wrapper for async ``GitHubAppClient.fetch_workflow_files``."""
    import redis.asyncio as aioredis

    from app.services.github.app_client import GitHubAppClient

    async def _fetch() -> list[WorkflowFileContent]:
        r = aioredis.from_url(settings.REDIS_URL)  # type: ignore[no-untyped-call]
        try:
            client = GitHubAppClient(redis_client=r)
            return list(await client.fetch_workflow_files(repo, ref=ref))
        finally:
            await r.aclose()

    return asyncio.run(_fetch())


def resolve_branch_head(repo: Repository, branch: str) -> str | None:
    """``branch``'s head commit SHA, or ``None`` if it can't be resolved.

    Never raises. A failure here degrades the sync to reading a mutable ref —
    worse, but still useful — whereas letting it propagate would fail a whole
    analysis over a lookup that is only there to make the read reproducible.
    ``None`` also covers the branch genuinely being gone, which the caller
    handles separately.
    """
    import redis.asyncio as aioredis

    from app.services.github.app_client import GitHubAppClient

    async def _resolve() -> str | None:
        r = aioredis.from_url(settings.REDIS_URL)  # type: ignore[no-untyped-call]
        try:
            client = GitHubAppClient(redis_client=r)
            token = await client.resolve_repo_token(repo)
            return await client.get_branch_head(token, repo.full_name, branch)
        finally:
            await r.aclose()

    try:
        return asyncio.run(_resolve())
    except Exception:
        logger.warning(
            "Could not resolve %s@%s; syncing off the mutable ref instead",
            repo.full_name,
            branch,
            exc_info=True,
        )
        return None


def content_of(wf_src: WorkflowFile | WorkflowFileContent) -> str:
    """The raw YAML, whichever of the two sources it came from."""
    return wf_src.raw_content if isinstance(wf_src, WorkflowFile) else wf_src.content


def sync_workflow_files(
    session: Session,
    repo: Repository,
    branch: str,
    *,
    fetch: Callable[..., Sequence[Any]] | None = None,
    resolve_sha: Callable[[Repository, str], str | None] | None = None,
    reconcile_missing: bool = True,
) -> WorkflowSyncResult:
    """Bring ``repo``'s ``WorkflowFile`` rows for ``branch`` in line with GitHub.

    ``fetch`` and ``resolve_sha`` default to this module's own functions and can
    be passed explicitly, so the analysis worker keeps its long-standing
    ``_fetch_workflow_files`` seam while everything else patches the names here.
    Either way a test can drive the whole reconciliation without a network.

    Raises ``WorkflowFetchError`` if the listing cannot be read at all — that is
    transient and the caller retries. Everything else is reported in the result.
    """
    # Resolved from module globals rather than bound as parameter defaults, so
    # that patching either name on this module works — a default is captured at
    # definition time and would ignore the patch.
    fetch = fetch or fetch_workflow_files_for_repo
    resolve_sha = resolve_sha or resolve_branch_head

    # Stamped *before* the resolve, so the cursor is never newer than the state
    # it describes: a concurrent sync that resolved later must win even if it
    # committed first.
    resolved_at = datetime.now(timezone.utc)
    head_sha = resolve_sha(repo, branch)

    try:
        fetched = list(fetch(repo, head_sha or branch))
    except Exception as exc:
        # Typed, because some failures here carry a useless message — a missing
        # GitHub App credential surfaces as a bare assertion whose whole text is
        # "None", which tells a reader nothing about where it came from.
        raise WorkflowFetchError(f"{type(exc).__name__}: {exc}") from exc

    # We could not pin the ref and the listing is empty. GitHub answers 404 both
    # for "this repo has no .github/workflows" and for "this ref does not
    # exist", and the fetcher maps both to []. Reconciling here would soft-delete
    # every workflow file on the branch and withdraw every fix targeting them,
    # off nothing more than a lookup failure.
    if head_sha is None and not fetched:
        logger.warning(
            "Sync for %s@%s: ref unresolved and no workflow files returned; "
            "skipping reconciliation rather than assuming they were all deleted",
            repo.full_name,
            branch,
        )
        return WorkflowSyncResult(
            branch=branch,
            head_sha=None,
            resolved_at=resolved_at,
            ref_unresolved=True,
        )

    result = WorkflowSyncResult(
        branch=branch, head_sha=head_sha, resolved_at=resolved_at
    )

    existing = {
        wf.path: wf
        for wf in session.exec(
            select(WorkflowFile)
            .where(WorkflowFile.repo_id == repo.id)
            .where(WorkflowFile.branch == branch)
        ).all()
    }

    for item in fetched:
        path = item.path
        content = content_of(item)
        content_hash = compute_content_hash(content)
        # The analysis input is what we just read, independent of whether the
        # row write below is allowed to land.
        result.contents[path] = content

        wf = existing.get(path)
        if wf is not None:
            if wf.fetched_at is not None and wf.fetched_at > resolved_at:
                # A sync that resolved a later commit already wrote this row.
                # Ours is the stale one: leave it, and hand the caller the newer
                # content rather than the older text we just read — analysing our
                # own read would put the staleness straight back into the issues.
                result.skipped_stale.append(path)
                result.contents[path] = wf.raw_content
                result.rows[path] = wf
                continue
            if wf.content_hash == content_hash:
                result.unchanged.append(path)
            else:
                result.updated.append(path)
                wf.content_hash = content_hash
                wf.raw_content = content
            if wf.deleted_at is not None:
                # The path is back on its branch: clear the soft-delete marker
                # so it shows in the static-analysis view again.
                wf.deleted_at = None
                result.restored.append(path)
            # Attempted whenever the path is present, not only when this sync is
            # the one that cleared `deleted_at`. A fix can be stranded in
            # `superseded_by_deleted_file` while its row's marker has already
            # been cleared by something else, and this is the only thing that
            # walks it back to `ready` (mirrors PR-reopen restoring a
            # closed-PR fix). `try_advance` is a no-op from any other state.
            if wf.fix is not None and sm.try_advance(wf.fix, sm.FixMachine, "restore"):
                session.add(wf.fix)
            # Provenance is refreshed even when the content did not change —
            # that is precisely what makes "unchanged" distinguishable from
            # "never checked".
            wf.fetched_at = resolved_at
            wf.source_commit_sha = head_sha
            session.add(wf)
        else:
            wf = WorkflowFile(
                repo_id=repo.id,
                branch=branch,
                path=path,
                content_hash=content_hash,
                raw_content=content,
                fetched_at=resolved_at,
                source_commit_sha=head_sha,
            )
            session.add(wf)
            result.added.append(path)

        result.rows[path] = wf

    session.flush()

    # If any write lost the ordering race, a newer sync already owns this
    # branch's state — including which paths are missing. Deciding deletions off
    # our older listing could withdraw a fix for a file that is present at the
    # newer head.
    if reconcile_missing and not result.skipped_stale:
        _reconcile_missing_paths(session, repo, branch, set(result.contents), result)

    # One transaction: content upserts and deletion reconciliation are a single
    # statement about the branch, and a crash between them would leave the row
    # set describing two different commits.
    session.commit()

    if any(result.counts[k] for k in ("added", "updated", "deleted", "restored")):
        logger.info(
            "Synced %s@%s at %s: %s",
            repo.full_name,
            branch,
            (head_sha or "unresolved")[:8],
            result.counts,
        )
    return result


def _reconcile_missing_paths(
    session: Session,
    repo: Repository,
    branch: str,
    fetched_paths: set[str],
    result: WorkflowSyncResult,
) -> None:
    """Reconcile workflow files that no longer exist on the synced branch.

    Soft-deletes the row (``deleted_at``) so it drops out of the
    static-analysis view and repo grade, resolves its open issues
    (``file_removed``), and withdraws any non-terminal fix targeting it, so a
    stale ``ready``/``delivered`` fix can't later resurrect content the user
    deliberately deleted. The row itself is kept (not hard-deleted) so its
    resolved issues and analysis history stay queryable, and so a re-added path
    can be cleanly restored. Scoped to the branch that was fetched: a feature
    branch missing a file says nothing about the default branch (and vice versa).
    """
    now = datetime.now(timezone.utc)
    wf_rows = session.exec(
        select(WorkflowFile)
        .where(WorkflowFile.repo_id == repo.id)
        .where(WorkflowFile.branch == branch)
    ).all()
    resolved = 0
    superseded = 0
    for wf in wf_rows:
        if wf.path in fetched_paths:
            continue
        if wf.deleted_at is None:
            wf.deleted_at = now
            session.add(wf)
            result.deleted.append(wf.path)
        open_issues = session.exec(
            select(Issue)
            .where(Issue.workflow_file_id == wf.id)
            .where(col(Issue.resolved_at).is_(None))
        ).all()
        for issue in open_issues:
            issue.resolved_at = now
            issue.resolution_reason = IssueResolutionReason.file_removed
            session.add(issue)
            resolved += 1
        if wf.fix is not None and sm.try_advance(
            wf.fix, sm.FixMachine, "supersede_deleted_file"
        ):
            session.add(wf.fix)
            superseded += 1
    if resolved or superseded or result.deleted:
        logger.info(
            "Soft-deleted %d workflow file(s), resolved %d issue(s) and "
            "superseded %d fix(es) for deleted workflow files in repo %s",
            len(result.deleted),
            resolved,
            superseded,
            repo.full_name,
        )
