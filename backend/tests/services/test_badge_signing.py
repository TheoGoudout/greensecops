"""Tests for badge URL signing helpers."""

import pytest

from app.core.config import settings
from app.services.badge_signing import (
    build_badge_svg_url,
    repo_badge_message,
    sign_badge,
    verify_badge,
)

# The signing key these digests were computed with. Pinned here rather than
# inherited from the environment: `sign_badge` is an HMAC over
# `settings.SECRET_KEY`, so with an ambient key these assertions fail on any
# machine whose .env differs — and fail claiming the *message format* changed,
# which is the one thing they are meant to detect.
_PINNED_KEY = "changethischangethischangethischangethischangethischangethischanget"

# Badge signatures are baked into URLs users paste into their READMEs, so a
# change to how a message is built silently breaks every badge already out
# there. These pin the three subject kinds against exactly that.
_PINNED = {
    repo_badge_message("acme", "web", "main"): "88ac476cdac520f86f20140118aa1b64",
    "11111111-1111-1111-1111-111111111111": "ab7c1e6f0b6c01a4f12265b0aa38a921",
    "22222222-2222-2222-2222-222222222222": "4f3ac07c37c2655a3f0e3e236729b7b4",
}


def test_signatures_are_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", _PINNED_KEY)
    for message, expected in _PINNED.items():
        assert sign_badge(message) == expected


def test_repo_badge_message_shape() -> None:
    assert repo_badge_message("acme", "web", "main") == "acme/web/main"


def test_sign_is_stable_and_message_specific() -> None:
    a = sign_badge(repo_badge_message("owner", "repo", "main"))
    assert a == sign_badge(repo_badge_message("owner", "repo", "main"))
    assert a != sign_badge(repo_badge_message("owner", "repo", "dev"))
    assert a != sign_badge(repo_badge_message("owner", "other", "main"))


def test_verify_roundtrip() -> None:
    message = repo_badge_message("owner", "repo", "main")
    sig = sign_badge(message)
    assert verify_badge(message, sig) is True
    assert verify_badge(message, "nope") is False
    assert verify_badge(message, None) is False
    assert verify_badge(repo_badge_message("owner", "repo", "dev"), sig) is False


def test_id_keyed_subjects_are_distinct() -> None:
    """A Terraform root and a Docker target are signed by bare row id, so two
    different ids must never share a signature."""
    assert sign_badge("root-1") == sign_badge("root-1")
    assert sign_badge("root-1") != sign_badge("root-2")


def test_build_url_signs_only_private() -> None:
    public = build_badge_svg_url("owner", "repo", "main", private=False)
    private = build_badge_svg_url("owner", "repo", "main", private=True)

    assert public.endswith("/badges/repositories/owner/repo/main.svg")
    assert "?sig=" not in public
    assert f"?sig={sign_badge(repo_badge_message('owner', 'repo', 'main'))}" in private
