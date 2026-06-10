import uuid

from sqlmodel import Session

from app.services.deduplication import compute_content_hash, is_duplicate


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
    duplicate, existing = is_duplicate(db, unique_hash)
    assert duplicate is False
    assert existing is None
