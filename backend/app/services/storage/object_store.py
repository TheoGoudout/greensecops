import logging
from functools import lru_cache
from typing import Any

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)


class ObjectStorageError(Exception):
    """Raised when the object store cannot be reached or returns an error."""


@lru_cache(maxsize=1)
def _get_client() -> Any:  # noqa: ANN401 — boto3 client has no public stub type
    kwargs: dict[str, Any] = {"region_name": settings.S3_REGION}

    if settings.S3_ENDPOINT_URL:
        # path-style addressing is required for MinIO (and most self-hosted
        # S3-compatible stores); virtual-hosted-style, boto3's default, only
        # resolves against real S3 DNS. Applied only alongside a custom
        # endpoint, since AWS is deprecating path-style for new buckets.
        kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
        kwargs["config"] = BotoConfig(s3={"addressing_style": "path"})

    # Passing an empty string would register *explicit* (and unusable)
    # credentials, shadowing the default chain; omitting the arguments
    # entirely is what lets an instance profile / task role authenticate.
    # Mirrors services/cloud/aws_collector.py's fallback.
    if settings.S3_ACCESS_KEY and settings.S3_SECRET_KEY:
        kwargs["aws_access_key_id"] = settings.S3_ACCESS_KEY
        kwargs["aws_secret_access_key"] = settings.S3_SECRET_KEY

    return boto3.client("s3", **kwargs)


def build_object_key(*parts: str) -> str:
    """Join key segments, stripping stray slashes so callers can't produce
    e.g. a double slash or an accidental leading "/" that would otherwise be
    interpreted as a key with an empty first segment."""
    cleaned = [p.strip("/") for p in parts if p.strip("/")]
    return "/".join(cleaned)


def ensure_bucket() -> None:
    """Create the configured bucket if it doesn't already exist. Idempotent —
    safe to call on every process start (see storage_pre_start.py)."""
    client = _get_client()
    try:
        client.head_bucket(Bucket=settings.S3_BUCKET)
        return
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status != 404:
            raise ObjectStorageError(
                f"Could not check bucket {settings.S3_BUCKET}: {exc}"
            ) from exc
    try:
        client.create_bucket(Bucket=settings.S3_BUCKET)
        logger.info("Created object storage bucket %s", settings.S3_BUCKET)
    except ClientError as exc:
        # A concurrent process (another replica booting at the same time) may
        # have created it between the head_bucket check and here.
        error_code = exc.response.get("Error", {}).get("Code")
        if error_code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            raise ObjectStorageError(
                f"Could not create bucket {settings.S3_BUCKET}: {exc}"
            ) from exc


def put_object(key: str, data: bytes, content_type: str = "application/json") -> None:
    client = _get_client()
    try:
        client.put_object(
            Bucket=settings.S3_BUCKET,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
    except (ClientError, BotoCoreError) as exc:
        raise ObjectStorageError(f"Failed to store object {key}: {exc}") from exc


def get_object(key: str) -> bytes | None:
    client = _get_client()
    try:
        response = client.get_object(Bucket=settings.S3_BUCKET, Key=key)
        return bytes(response["Body"].read())
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")
        if error_code in ("NoSuchKey", "404"):
            return None
        raise ObjectStorageError(f"Failed to fetch object {key}: {exc}") from exc
    except BotoCoreError as exc:
        raise ObjectStorageError(f"Failed to fetch object {key}: {exc}") from exc


def delete_object(key: str) -> None:
    client = _get_client()
    try:
        client.delete_object(Bucket=settings.S3_BUCKET, Key=key)
    except (ClientError, BotoCoreError) as exc:
        raise ObjectStorageError(f"Failed to delete object {key}: {exc}") from exc
