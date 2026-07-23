from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from app.services.storage import object_store


def _client_error(code: str, status: int) -> ClientError:
    return ClientError(
        {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}},
        "TestOperation",
    )


def test_build_object_key_strips_stray_slashes() -> None:
    assert object_store.build_object_key("terraform", "root-1", "plan.json") == (
        "terraform/root-1/plan.json"
    )
    assert object_store.build_object_key("/terraform/", "//root-1//", "plan.json") == (
        "terraform/root-1/plan.json"
    )


def test_build_object_key_drops_empty_segments() -> None:
    assert object_store.build_object_key("terraform", "", "plan.json") == (
        "terraform/plan.json"
    )


def test_ensure_bucket_is_a_noop_when_bucket_already_exists() -> None:
    client = MagicMock()
    with patch.object(object_store, "_get_client", return_value=client):
        object_store.ensure_bucket()

    client.head_bucket.assert_called_once()
    client.create_bucket.assert_not_called()


def test_ensure_bucket_creates_it_when_missing() -> None:
    client = MagicMock()
    client.head_bucket.side_effect = _client_error("404", 404)
    with patch.object(object_store, "_get_client", return_value=client):
        object_store.ensure_bucket()

    client.create_bucket.assert_called_once()


def test_ensure_bucket_tolerates_concurrent_creation() -> None:
    client = MagicMock()
    client.head_bucket.side_effect = _client_error("404", 404)
    client.create_bucket.side_effect = _client_error("BucketAlreadyOwnedByYou", 409)
    with patch.object(object_store, "_get_client", return_value=client):
        object_store.ensure_bucket()  # must not raise


def test_ensure_bucket_raises_on_other_head_bucket_error() -> None:
    client = MagicMock()
    client.head_bucket.side_effect = _client_error("AccessDenied", 403)
    with (
        patch.object(object_store, "_get_client", return_value=client),
        pytest.raises(object_store.ObjectStorageError),
    ):
        object_store.ensure_bucket()


def test_put_object_uploads_bytes_with_content_type() -> None:
    client = MagicMock()
    with patch.object(object_store, "_get_client", return_value=client):
        object_store.put_object("terraform/root-1/plan.json", b"{}", "application/json")

    client.put_object.assert_called_once_with(
        Bucket=object_store.settings.S3_BUCKET,
        Key="terraform/root-1/plan.json",
        Body=b"{}",
        ContentType="application/json",
    )


def test_put_object_wraps_client_errors() -> None:
    client = MagicMock()
    client.put_object.side_effect = _client_error("InternalError", 500)
    with (
        patch.object(object_store, "_get_client", return_value=client),
        pytest.raises(object_store.ObjectStorageError),
    ):
        object_store.put_object("some/key", b"data")


def test_get_object_returns_bytes() -> None:
    body = MagicMock()
    body.read.return_value = b"payload"
    client = MagicMock()
    client.get_object.return_value = {"Body": body}
    with patch.object(object_store, "_get_client", return_value=client):
        result = object_store.get_object("some/key")

    assert result == b"payload"


def test_get_object_returns_none_when_missing() -> None:
    client = MagicMock()
    client.get_object.side_effect = _client_error("NoSuchKey", 404)
    with patch.object(object_store, "_get_client", return_value=client):
        assert object_store.get_object("missing/key") is None


def test_get_object_raises_on_other_errors() -> None:
    client = MagicMock()
    client.get_object.side_effect = _client_error("AccessDenied", 403)
    with (
        patch.object(object_store, "_get_client", return_value=client),
        pytest.raises(object_store.ObjectStorageError),
    ):
        object_store.get_object("some/key")


def test_delete_object_wraps_client_errors() -> None:
    client = MagicMock()
    client.delete_object.side_effect = _client_error("InternalError", 500)
    with (
        patch.object(object_store, "_get_client", return_value=client),
        pytest.raises(object_store.ObjectStorageError),
    ):
        object_store.delete_object("some/key")
