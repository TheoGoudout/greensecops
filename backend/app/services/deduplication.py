import hashlib
import uuid

from sqlmodel import Session, col, select

from app.models import ScanStatus, WorkflowScan


def compute_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def compute_fingerprint(
    scope_id: uuid.UUID, rule_id: uuid.UUID, *parts: str | int | None
) -> str:
    """Stable 16-char hex identity for a violation, scoped to ``scope_id``.

    This is what an upsert matches on across re-runs, so a recurring violation
    updates its existing row and keeps its resolved/ignored history instead of
    inserting a duplicate. The scope is always the thing a violation persists
    *against* — a workflow file, a Terraform root, a Docker target, a cloud
    account — never a single analysis or scan, which is why that history
    survives a re-scan at all.

    ``parts`` are the locators that distinguish two violations of the same
    rule within one scope, and each engine passes its own:

    - workflow: ``(job, step_index, discriminator)``. The step's *position*
      keys the hash, not its action reference, so two steps using the same
      action stay distinct.
    - terraform: ``(resource_address, discriminator)``.
    - docker: ``(file_path, discriminator)`` — a Dockerfile has no addressable
      resources, so the file is the unit a rule fires against.
    - cloud: ``(resource_id, discriminator)``.

    A ``discriminator`` is what a rule that can fire twice at the same locator
    supplies to keep the two apart: the env var name for ``hardcoded_secrets``,
    the service name for a Compose rule, the stage name for a Dockerfile rule.
    It must **never** be a line number — an unrelated edit higher up the file
    shifts every line below it and would orphan each finding's history on the
    next scan.

    ``None`` renders as an empty segment, so an absent locator and an empty one
    produce the same key. That is deliberate: a rule either reports a locator
    or it does not.

    The key layout is load-bearing. Every fingerprint already in the database
    was derived from it, so changing the joined string orphans every existing
    row; ``tests/services/test_deduplication.py`` pins the output of every call
    shape against exactly that risk.
    """
    segments = [str(scope_id), str(rule_id)]
    segments += ["" if part is None else str(part) for part in parts]
    return hashlib.sha256(":".join(segments).encode()).hexdigest()[:16]


def find_completed_analysis(
    session: Session,
    content_hash: str,
    repo_id: uuid.UUID,
    branch: str,
) -> WorkflowScan | None:
    """Return the branch's most recent completed analysis for this content hash.

    Scoped to the repository *and* branch: identical workflow content in two
    different repositories must not share analyses (issues and workflow files
    belong to a single repo), and identical content on two branches of the same
    repo must not either — a dedup-skip would leave the other branch's
    WorkflowFile row and issue reconciliation stale (e.g. right after a merge).
    """
    return session.exec(
        select(WorkflowScan)
        .where(WorkflowScan.content_hash == content_hash)
        .where(WorkflowScan.repo_id == repo_id)
        .where(WorkflowScan.branch == branch)
        .where(WorkflowScan.status == ScanStatus.completed)
        .order_by(col(WorkflowScan.created_at).desc())
    ).first()


def is_duplicate(
    session: Session, content_hash: str, repo_id: uuid.UUID, branch: str
) -> tuple[bool, WorkflowScan | None]:
    existing = find_completed_analysis(session, content_hash, repo_id, branch)
    return (existing is not None, existing)
