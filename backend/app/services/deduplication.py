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
) -> Analysis | None:
    """Return the most recent completed analysis for this content hash, or None."""
    return session.exec(
        select(Analysis)
        .where(Analysis.content_hash == content_hash)
        .where(Analysis.status == AnalysisStatus.completed)
        .order_by(Analysis.created_at.desc())  # type: ignore[arg-type]
    ).first()


def is_duplicate(session: Session, content_hash: str) -> tuple[bool, Analysis | None]:
    existing = find_completed_analysis(session, content_hash)
    return (existing is not None, existing)
