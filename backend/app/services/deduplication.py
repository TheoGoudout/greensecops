import hashlib
import uuid

from sqlmodel import Session, col, select

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


def compute_terraform_finding_fingerprint(
    terraform_root_id: uuid.UUID,
    rule_id: uuid.UUID,
    resource_address: str | None,
    discriminator: str | None = None,
) -> str:
    """Stable 16-char hex key for (root, rule, resource_address[, discriminator]).

    The Terraform analogue of ``compute_issue_fingerprint``: identifies a
    finding across scan re-runs. Scoped to the root (not one scan) the same
    way an Issue's fingerprint is scoped to its workflow file, not one
    Analysis — a re-scan must recognize "the same" finding to keep its
    resolved/ignored history rather than creating a duplicate row.
    """
    disc_part = "" if discriminator is None else discriminator
    key = f"{terraform_root_id}:{rule_id}:{resource_address or ''}:{disc_part}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def compute_cloud_finding_fingerprint(
    cloud_account_id: uuid.UUID,
    rule_id: uuid.UUID,
    resource_id: str,
    discriminator: str | None = None,
) -> str:
    """Stable 16-char hex key for (account, rule, resource_id[, discriminator]).

    The cloud-posture analogue of ``compute_terraform_finding_fingerprint``:
    scoped to the account (not one scan), so re-scans recognize "the same"
    finding across the resource's lifetime rather than creating a duplicate.
    """
    disc_part = "" if discriminator is None else discriminator
    key = f"{cloud_account_id}:{rule_id}:{resource_id}:{disc_part}"
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
        .order_by(col(Analysis.created_at).desc())
    ).first()


def is_duplicate(
    session: Session, content_hash: str, repo_id: uuid.UUID, branch: str
) -> tuple[bool, Analysis | None]:
    existing = find_completed_analysis(session, content_hash, repo_id, branch)
    return (existing is not None, existing)
