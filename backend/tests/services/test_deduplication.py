import uuid

import pytest
from sqlmodel import Session

from app.services.deduplication import (
    compute_content_hash,
    compute_fingerprint,
    is_duplicate,
)

# A fingerprint is the persisted identity of an issue/finding across re-runs:
# it is what an upsert matches on to keep a row's resolved/ignored history
# instead of inserting a duplicate. Changing how one is derived silently
# orphans every existing row, so these pin the exact output of every call
# shape. A failure here means a refactor changed the hash — not that the
# expectation needs updating.
_SCOPE = uuid.UUID("11111111-1111-1111-1111-111111111111")
_RULE = uuid.UUID("22222222-2222-2222-2222-222222222222")

_PINNED = [
    (
        "issue-full",
        lambda: compute_fingerprint(_SCOPE, _RULE, "build", 3, "TOKEN"),
        "f8d605fdf6e09e2f",
    ),
    (
        "issue-no-job",
        lambda: compute_fingerprint(_SCOPE, _RULE, None, 3, "TOKEN"),
        "883e48799cf9cacd",
    ),
    (
        "issue-no-step",
        lambda: compute_fingerprint(_SCOPE, _RULE, "build", None, "TOKEN"),
        "6b510f6cb46711b9",
    ),
    (
        "issue-no-disc",
        lambda: compute_fingerprint(_SCOPE, _RULE, "build", 3, None),
        "1e3677ff3a47f991",
    ),
    (
        "issue-step-0",
        lambda: compute_fingerprint(_SCOPE, _RULE, "build", 0, None),
        "b437db979390ba16",
    ),
    (
        "issue-all-none",
        lambda: compute_fingerprint(_SCOPE, _RULE, None, None, None),
        "731494a41ea2083c",
    ),
    (
        "tf-full",
        lambda: compute_fingerprint(_SCOPE, _RULE, "aws_s3_bucket.logs", "d"),
        "00f295428806846d",
    ),
    (
        "tf-no-addr",
        lambda: compute_fingerprint(_SCOPE, _RULE, None, "d"),
        "68f7c84b8506a68a",
    ),
    (
        "tf-no-disc",
        lambda: compute_fingerprint(_SCOPE, _RULE, "aws_s3_bucket.logs", None),
        "79b906a688a7d0bf",
    ),
    (
        "docker-full",
        lambda: compute_fingerprint(_SCOPE, _RULE, "Dockerfile", "web"),
        "090b9257c48c84c8",
    ),
    (
        "docker-no-disc",
        lambda: compute_fingerprint(_SCOPE, _RULE, "Dockerfile", None),
        "6f7258145fdf5048",
    ),
    (
        "cloud-full",
        lambda: compute_fingerprint(_SCOPE, _RULE, "arn:aws:s3:::b", "d"),
        "5e9f072fc79fb695",
    ),
    (
        "cloud-no-disc",
        lambda: compute_fingerprint(_SCOPE, _RULE, "arn:aws:s3:::b", None),
        "aab6cd8cd2c9066f",
    ),
]


@pytest.mark.parametrize(
    ("compute", "expected"),
    [(c, e) for _, c, e in _PINNED],
    ids=[n for n, _, _ in _PINNED],
)
def test_fingerprint_output_is_pinned(compute: object, expected: str) -> None:
    assert compute() == expected  # type: ignore[operator]


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
    fp1 = compute_fingerprint(wf_id, rule_id, "build", 2)
    fp2 = compute_fingerprint(wf_id, rule_id, "build", 2)
    assert fp1 == fp2
    assert len(fp1) == 16
    int(fp1, 16)  # hex


def test_fingerprint_distinct_per_step_index() -> None:
    # Two steps using the same action in one job must not collide.
    wf_id, rule_id = uuid.uuid4(), uuid.uuid4()
    fp1 = compute_fingerprint(wf_id, rule_id, "build", 0)
    fp2 = compute_fingerprint(wf_id, rule_id, "build", 3)
    assert fp1 != fp2


def test_fingerprint_index_zero_differs_from_none() -> None:
    # A violation on the first step is not a job-level violation.
    wf_id, rule_id = uuid.uuid4(), uuid.uuid4()
    fp_first_step = compute_fingerprint(wf_id, rule_id, "build", 0)
    fp_job_level = compute_fingerprint(wf_id, rule_id, "build", None)
    assert fp_first_step != fp_job_level


def test_docker_fingerprint_stable_for_same_inputs() -> None:
    target_id, rule_id = uuid.uuid4(), uuid.uuid4()
    fp1 = compute_fingerprint(target_id, rule_id, "backend/Dockerfile")
    fp2 = compute_fingerprint(target_id, rule_id, "backend/Dockerfile")
    assert fp1 == fp2
    assert len(fp1) == 16
    int(fp1, 16)  # hex


def test_docker_fingerprint_distinct_per_file() -> None:
    # The same rule firing on two Dockerfiles in one target is two findings.
    target_id, rule_id = uuid.uuid4(), uuid.uuid4()
    fp1 = compute_fingerprint(target_id, rule_id, "backend/Dockerfile")
    fp2 = compute_fingerprint(target_id, rule_id, "frontend/Dockerfile")
    assert fp1 != fp2


def test_docker_fingerprint_distinct_per_discriminator() -> None:
    # Two privileged services in one compose file must not collide.
    target_id, rule_id = uuid.uuid4(), uuid.uuid4()
    fp1 = compute_fingerprint(target_id, rule_id, "compose.yml", "api")
    fp2 = compute_fingerprint(target_id, rule_id, "compose.yml", "worker")
    assert fp1 != fp2


def test_docker_fingerprint_scoped_to_the_target() -> None:
    rule_id = uuid.uuid4()
    fp1 = compute_fingerprint(uuid.uuid4(), rule_id, "Dockerfile")
    fp2 = compute_fingerprint(uuid.uuid4(), rule_id, "Dockerfile")
    assert fp1 != fp2
