"""Tests for the pieces every scan worker shares.

``scan_lock`` is used by all four scan workers, so its release semantics are
worth pinning directly rather than only through one worker's task test — in
particular that a scan raising mid-run still frees the lock, which is what
stops one crashed worker from blocking a target until the TTL expires.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.services.scan_support import (
    CLOUD_SCAN_LOCK_TTL_SECONDS,
    SCAN_LOCK_TTL_SECONDS,
    scan_lock,
)


def _fake_redis(acquired: bool = True) -> MagicMock:
    client = MagicMock()
    client.set.return_value = acquired
    return client


def test_lock_is_namespaced_and_released() -> None:
    client = _fake_redis()
    with patch(
        "app.services.scan_support.redis_sync.Redis.from_url", return_value=client
    ):
        with scan_lock("docker_scan:abc") as acquired:
            assert acquired is True

    client.set.assert_called_once_with(
        "greensecops:lock:docker_scan:abc", "1", nx=True, ex=SCAN_LOCK_TTL_SECONDS
    )
    client.delete.assert_called_once_with("greensecops:lock:docker_scan:abc")
    client.close.assert_called_once()


def test_lock_released_when_the_scan_raises() -> None:
    """A worker that dies mid-scan must not hold its target hostage."""
    client = _fake_redis()
    with patch(
        "app.services.scan_support.redis_sync.Redis.from_url", return_value=client
    ):
        with pytest.raises(RuntimeError), scan_lock("terraform_scan:xyz"):
            raise RuntimeError("scan blew up")

    client.delete.assert_called_once()
    client.close.assert_called_once()


def test_a_lock_we_did_not_take_is_not_deleted() -> None:
    """Losing the race must not delete the *winner's* key on the way out."""
    client = _fake_redis(acquired=False)
    with patch(
        "app.services.scan_support.redis_sync.Redis.from_url", return_value=client
    ):
        with scan_lock("cloud_scan:1", CLOUD_SCAN_LOCK_TTL_SECONDS) as acquired:
            assert acquired is False

    client.delete.assert_not_called()
    client.close.assert_called_once()


def test_cloud_scans_get_a_longer_lease() -> None:
    """A cloud sweep is bounded by the AWS API, not by file count."""
    assert CLOUD_SCAN_LOCK_TTL_SECONDS > SCAN_LOCK_TTL_SECONDS
