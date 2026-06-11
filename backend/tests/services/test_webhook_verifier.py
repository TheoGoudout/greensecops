import hashlib
import hmac

from app.services.github.webhook_verifier import verify_webhook_signature


def test_valid_signature() -> None:
    payload = b'{"action": "push"}'
    secret = "my-webhook-secret"
    sig = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(payload, sig, secret) is True


def test_invalid_signature() -> None:
    payload = b'{"action": "push"}'
    assert verify_webhook_signature(payload, "sha256=deadbeef", "secret") is False


def test_missing_signature() -> None:
    assert verify_webhook_signature(b"payload", None, "secret") is False


def test_wrong_prefix() -> None:
    assert verify_webhook_signature(b"payload", "md5=abc123", "secret") is False


def test_tampered_payload() -> None:
    secret = "my-webhook-secret"
    original = b'{"action": "push"}'
    tampered = b'{"action": "delete"}'
    sig = "sha256=" + hmac.new(secret.encode(), original, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(tampered, sig, secret) is False
