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
    step_index: int | None,
    discriminator: str | None = None,
) -> str:
    """Stable 16-char hex key for (workflow_file, rule, job, step_index[, discriminator]).

    Used as the unique identity of an issue across analysis re-runs. The
    step's position in the job (not its action reference) keys the hash so
    two steps using the same action get distinct fingerprints.

    discriminator is set by rules that can fire multiple times at the same
    (job, step_index) — e.g. hardcoded_secrets uses the env var name so that
    two different secrets in the same step produce distinct fingerprints.
    """
    step_part = "" if step_index is None else step_index
    disc_part = "" if discriminator is None else discriminator
    key = f"{workflow_file_id}:{rule_id}:{job or ''}:{step_part}:{disc_part}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def find_completed_analysis(
    session: Session,
    content_hash: str,
    repo_id: uuid.UUID,
    branch: str,
) -> Analysis | None:
    """Return the branch's most recent completed analysis for this content hash.

    Scoped to the repository *and* branch: identical workflow content in two
    different repositories must not share analyses (issues and workflow files
    belong to a single repo), and identical content on two branches of the same
    repo must not either — a dedup-skip would leave the other branch's
    WorkflowFile row and issue reconciliation stale (e.g. right after a merge).
    """
    return session.exec(
        select(Analysis)
        .where(Analysis.content_hash == content_hash)
        .where(Analysis.repo_id == repo_id)
        .where(Analysis.branch == branch)
        .where(Analysis.status == AnalysisStatus.completed)
        .order_by(Analysis.created_at.desc())  # type: ignore[arg-type]
    ).first()


def is_duplicate(
    session: Session, content_hash: str, repo_id: uuid.UUID, branch: str
) -> tuple[bool, Analysis | None]:
    existing = find_completed_analysis(session, content_hash, repo_id, branch)
    return (existing is not None, existing)
