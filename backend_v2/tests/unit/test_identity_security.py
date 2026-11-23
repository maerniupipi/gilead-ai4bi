"""Pure identity security tests."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import pytest

from xiaoying_quick.modules.identity.contracts import AuthenticatedPrincipal, Role
from xiaoying_quick.modules.identity.security import HMACTokenService, PasswordHasher
from xiaoying_quick.shared.clock import FrozenClock
from xiaoying_quick.shared.errors import InvalidToken


def _payload(token: str) -> dict[str, object]:
    raw = token.split(".")[1]
    padding = "=" * (-len(raw) % 4)
    decoded = json.loads(base64.urlsafe_b64decode(raw + padding))
    assert isinstance(decoded, dict)
    return decoded


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="usr_1",
        username="alice",
        display_name="Alice",
        role=Role.USER,
    )


def test_password_digest_is_salted_and_verifiable() -> None:
    hasher = PasswordHasher(iterations=100_000)
    first = hasher.hash("same-password")
    second = hasher.hash("same-password")

    assert first != second
    assert "same-password" not in first
    assert hasher.verify("same-password", first)
    assert not hasher.verify("wrong-password", first)


def test_hmac_token_detects_tampering_and_expiry() -> None:
    issued_at = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)
    clock = FrozenClock(issued_at)
    issuer = HMACTokenService(
        secret="a-test-signing-secret-with-more-than-32-bytes",
        issuer="test",
        ttl_seconds=60,
        clock=clock,
    )
    principal = _principal()
    token, _ = issuer.issue(principal)
    claims = issuer.verify(token)
    assert claims.subject == principal.user_id

    header, payload, signature = token.split(".")
    changed_payload = ("A" if payload[0] != "A" else "B") + payload[1:]
    with pytest.raises(InvalidToken):
        issuer.verify(f"{header}.{changed_payload}.{signature}")

    expired_verifier = HMACTokenService(
        secret="a-test-signing-secret-with-more-than-32-bytes",
        issuer="test",
        ttl_seconds=60,
        clock=FrozenClock(issued_at + timedelta(seconds=61)),
    )
    with pytest.raises(InvalidToken, match="expired"):
        expired_verifier.verify(token)


def test_hmac_token_ttl_zero_never_expires() -> None:
    issued_at = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)
    issuer = HMACTokenService(
        secret="a-test-signing-secret-with-more-than-32-bytes",
        issuer="test",
        ttl_seconds=0,
        clock=FrozenClock(issued_at),
    )
    token, expires_at = issuer.issue(_principal())
    assert expires_at is None
    assert "exp" not in _payload(token)

    later = HMACTokenService(
        secret="a-test-signing-secret-with-more-than-32-bytes",
        issuer="test",
        ttl_seconds=0,
        clock=FrozenClock(issued_at + timedelta(days=3650)),
    )
    claims = later.verify(token)
    assert claims.subject == "usr_1"
    assert claims.expires_at is None


def test_hmac_token_rejects_negative_ttl() -> None:
    with pytest.raises(ValueError, match="ttl_seconds"):
        HMACTokenService(
            secret="a-test-signing-secret-with-more-than-32-bytes",
            issuer="test",
            ttl_seconds=-1,
        )


def test_admin_role_grants_other_roles_but_user_does_not() -> None:
    assert Role.ADMIN.grants(Role.DATA_SOURCE_ADMIN)
    assert Role.ADMIN.grants(Role.KNOWLEDGE_REVIEWER)
    assert not Role.USER.grants(Role.ADMIN)
