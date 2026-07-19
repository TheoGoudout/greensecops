import uuid

from sqlmodel import Session

from app.services.deduplication import (
    compute_content_hash,
    compute_issue_fingerprint,
    is_duplicate,
)


def test_compute_content_hash_deterministic() -> None:
    content = "name: CI\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
    h1 = compute_content_hash(content)
    h2 = compute_content_hash(content)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex = 64 chars


def test_compute_content_hash_different_content() -> None:
    h1 = compute_content_hash("content A")
    h2 = compute_content_hash("content B")
    assert h1 != h2


def test_is_duplicate_no_match(db: Session) -> None:
    unique_hash = compute_content_hash(f"unique-{uuid.uuid4()}")
    duplicate, existing = is_duplicate(db, unique_hash, uuid.uuid4(), "main")
    assert duplicate is False
    assert existing is None


def test_fingerprint_stable_for_same_inputs() -> None:
    wf_id, rule_id = uuid.uuid4(), uuid.uuid4()
    fp1 = compute_issue_fingerprint(wf_id, rule_id, "build", 2)
    fp2 = compute_issue_fingerprint(wf_id, rule_id, "build", 2)
    assert fp1 == fp2
    assert len(fp1) == 16
    int(fp1, 16)  # hex


def test_fingerprint_distinct_per_step_index() -> None:
    # Two steps using the same action in one job must not collide.
    wf_id, rule_id = uuid.uuid4(), uuid.uuid4()
    fp1 = compute_issue_fingerprint(wf_id, rule_id, "build", 0)
    fp2 = compute_issue_fingerprint(wf_id, rule_id, "build", 3)
    assert fp1 != fp2


def test_fingerprint_index_zero_differs_from_none() -> None:
    # A violation on the first step is not a job-level violation.
    wf_id, rule_id = uuid.uuid4(), uuid.uuid4()
    fp_first_step = compute_issue_fingerprint(wf_id, rule_id, "build", 0)
    fp_job_level = compute_issue_fingerprint(wf_id, rule_id, "build", None)
    assert fp_first_step != fp_job_level
