import hashlib
import uuid

from sqlmodel import Session, select

from app.models import Analysis, AnalysisStatus


def compute_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def compute_issue_fingerprint(
    workflow_file_id: uuid.UUID,
    rule_id: uuid.UUID,
    job: str | None,
    step: str | None,
) -> str:
    """Stable 16-char hex key for (workflow_file, rule, job, step).

    Used as the unique identity of an issue across analysis re-runs.
    """
    key = f"{workflow_file_id}:{rule_id}:{job or ''}:{step or ''}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def find_completed_analysis(
    session: Session,
    content_hash: str,
    repo_id: uuid.UUID,
) -> Analysis | None:
    """Return the repo's most recent completed analysis for this content hash.

    Scoped to the repository: identical workflow content in two different
    repositories must not share analyses (issues and workflow files belong to
    a single repo).
    """
    return session.exec(
        select(Analysis)
        .where(Analysis.content_hash == content_hash)
        .where(Analysis.repo_id == repo_id)
        .where(Analysis.status == AnalysisStatus.completed)
        .order_by(Analysis.created_at.desc())  # type: ignore[arg-type]
    ).first()


def is_duplicate(
    session: Session, content_hash: str, repo_id: uuid.UUID
) -> tuple[bool, Analysis | None]:
    existing = find_completed_analysis(session, content_hash, repo_id)
    return (existing is not None, existing)
