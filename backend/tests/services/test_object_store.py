from collections.abc import Iterator
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


@pytest.fixture
def _uncached_client() -> Iterator[MagicMock]:
    """Yield a patched boto3.client with _get_client's lru_cache cleared.

    _get_client memoises the client for the process, so a test that changes
    the S3_* settings has to drop the cached instance on both sides of the
    call or it leaks into (and inherits from) its neighbours.
    """
    object_store._get_client.cache_clear()
    with patch.object(object_store.boto3, "client") as boto_client:
        yield boto_client
    object_store._get_client.cache_clear()


def test_get_client_uses_path_style_and_explicit_keys_for_minio(
    _uncached_client: MagicMock,
) -> None:
    with patch.multiple(
        object_store.settings,
        S3_ENDPOINT_URL="http://minio:9000",
        S3_ACCESS_KEY="minio-user",
        S3_SECRET_KEY="minio-password",
        S3_REGION="us-east-1",
    ):
        object_store._get_client()

    _, kwargs = _uncached_client.call_args
    assert kwargs["endpoint_url"] == "http://minio:9000"
    assert kwargs["aws_access_key_id"] == "minio-user"
    assert kwargs["aws_secret_access_key"] == "minio-password"
    assert kwargs["config"].s3 == {"addressing_style": "path"}


def test_get_client_falls_back_to_default_credential_chain_for_real_s3(
    _uncached_client: MagicMock,
) -> None:
    """No endpoint and no keys: boto3 must resolve AWS S3 and the instance role."""
    with patch.multiple(
        object_store.settings,
        S3_ENDPOINT_URL=None,
        S3_ACCESS_KEY=None,
        S3_SECRET_KEY=None,
        S3_REGION="eu-west-1",
    ):
        object_store._get_client()

    _, kwargs = _uncached_client.call_args
    assert kwargs == {"region_name": "eu-west-1"}


def test_get_client_ignores_a_half_configured_key_pair(
    _uncached_client: MagicMock,
) -> None:
    """An access key without its secret is unusable; don't shadow the chain."""
    with patch.multiple(
        object_store.settings,
        S3_ENDPOINT_URL="",
        S3_ACCESS_KEY="orphaned-key",
        S3_SECRET_KEY="",
        S3_REGION="us-east-1",
    ):
        object_store._get_client()

    _, kwargs = _uncached_client.call_args
    assert "aws_access_key_id" not in kwargs
    assert "endpoint_url" not in kwargs
