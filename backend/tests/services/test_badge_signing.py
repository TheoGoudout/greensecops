"""Tests for badge URL signing helpers."""

from app.services.badge_signing import (
    build_badge_svg_url,
    sign_badge,
    sign_terraform_root_badge,
    verify_badge,
    verify_terraform_root_badge,
)


def test_sign_is_stable_and_branch_specific() -> None:
    a = sign_badge("owner", "repo", "main")
    assert a == sign_badge("owner", "repo", "main")
    assert a != sign_badge("owner", "repo", "dev")
    assert a != sign_badge("owner", "other", "main")


def test_verify_roundtrip() -> None:
    sig = sign_badge("owner", "repo", "main")
    assert verify_badge("owner", "repo", "main", sig) is True
    assert verify_badge("owner", "repo", "main", "nope") is False
    assert verify_badge("owner", "repo", "main", None) is False
    assert verify_badge("owner", "repo", "dev", sig) is False


def test_build_url_signs_only_private() -> None:
    public = build_badge_svg_url("owner", "repo", "main", private=False)
    private = build_badge_svg_url("owner", "repo", "main", private=True)

    assert public.endswith("/badges/owner/repo/main.svg")
    assert "?sig=" not in public
    assert f"?sig={sign_badge('owner', 'repo', 'main')}" in private


def test_terraform_root_sign_is_stable_and_id_specific() -> None:
    a = sign_terraform_root_badge("root-1")
    assert a == sign_terraform_root_badge("root-1")
    assert a != sign_terraform_root_badge("root-2")


def test_terraform_root_verify_roundtrip() -> None:
    sig = sign_terraform_root_badge("root-1")
    assert verify_terraform_root_badge("root-1", sig) is True
    assert verify_terraform_root_badge("root-1", "nope") is False
    assert verify_terraform_root_badge("root-1", None) is False
    assert verify_terraform_root_badge("root-2", sig) is False
