"""Password hashing and compact HMAC-signed bearer tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from xiaoying_quick.modules.identity.contracts import AuthenticatedPrincipal, Role, TokenClaims
from xiaoying_quick.shared.clock import Clock, SystemClock
from xiaoying_quick.shared.errors import InvalidToken, ValidationFailed


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


class PasswordHasher:
    """Versioned PBKDF2-HMAC password digest using only the standard library."""

    algorithm = "pbkdf2_sha256"

    def __init__(self, *, iterations: int = 600_000) -> None:
        if not 100_000 <= iterations <= 2_000_000:
            raise ValueError("PBKDF2 iterations outside the supported safety range")
        self.iterations = iterations

    def hash(self, password: str) -> str:
        encoded = password.encode("utf-8")
        if not 8 <= len(encoded) <= 1024:
            raise ValidationFailed("password must contain between 8 and 1024 UTF-8 bytes")
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", encoded, salt, self.iterations)
        return "$".join(
            (self.algorithm, str(self.iterations), _b64encode(salt), _b64encode(digest))
        )

    def verify(self, password: str, encoded_digest: str) -> bool:
        try:
            algorithm, raw_iterations, raw_salt, raw_digest = encoded_digest.split("$", 3)
            iterations = int(raw_iterations)
            if algorithm != self.algorithm or not 100_000 <= iterations <= 2_000_000:
                return False
            salt = _b64decode(raw_salt)
            expected = _b64decode(raw_digest)
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError):
            return False


class HMACTokenService:
    """Issues and verifies a deliberately small HS256 JWT profile."""

    def __init__(
        self,
        *,
        secret: str,
        issuer: str,
        ttl_seconds: int,
        clock: Clock | None = None,
    ) -> None:
        key = secret.encode("utf-8")
        if len(key) < 32:
            raise ValueError("HMAC signing secret must contain at least 32 bytes")
        if ttl_seconds < 0:
            raise ValueError("HMAC token ttl_seconds must be >= 0")
        self._key = key
        self._issuer = issuer
        self._ttl = None if ttl_seconds == 0 else timedelta(seconds=ttl_seconds)
        self._clock = clock or SystemClock()

    def issue(self, principal: AuthenticatedPrincipal) -> tuple[str, datetime | None]:
        issued_at = self._clock.now().astimezone(timezone.utc)
        header = {"alg": "HS256", "typ": "JWT"}
        payload: dict[str, Any] = {
            "iss": self._issuer,
            "sub": principal.user_id,
            "usr": principal.username,
            "role": principal.role.value,
            "iat": int(issued_at.timestamp()),
            "jti": secrets.token_urlsafe(16),
        }
        expires_at: datetime | None
        if self._ttl is None:
            expires_at = None
        else:
            expires_at = issued_at + self._ttl
            payload["exp"] = int(expires_at.timestamp())
        encoded_header = self._encode_json(header)
        encoded_payload = self._encode_json(payload)
        signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
        signature = hmac.new(self._key, signing_input, hashlib.sha256).digest()
        return f"{signing_input.decode('ascii')}.{_b64encode(signature)}", expires_at

    def verify(self, token: str) -> TokenClaims:
        try:
            encoded_header, encoded_payload, encoded_signature = token.split(".")
            signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
            actual_signature = _b64decode(encoded_signature)
            expected_signature = hmac.new(self._key, signing_input, hashlib.sha256).digest()
            if not hmac.compare_digest(actual_signature, expected_signature):
                raise InvalidToken("token signature is invalid")

            header = self._decode_json(encoded_header)
            payload = self._decode_json(encoded_payload)
            if header != {"alg": "HS256", "typ": "JWT"}:
                raise InvalidToken("unsupported token header")
            claims = self._validate_payload(payload)
            return claims
        except InvalidToken:
            raise
        except Exception as exc:
            raise InvalidToken("token is malformed") from exc

    @staticmethod
    def _encode_json(value: dict[str, Any]) -> str:
        raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return _b64encode(raw)

    @staticmethod
    def _decode_json(value: str) -> dict[str, Any]:
        decoded = json.loads(_b64decode(value))
        if not isinstance(decoded, dict):
            raise InvalidToken("token section must be an object")
        return decoded

    def _validate_payload(self, payload: dict[str, Any]) -> TokenClaims:
        try:
            issuer = payload["iss"]
            subject = payload["sub"]
            username = payload["usr"]
            role = Role(payload["role"])
            issued_timestamp = int(payload["iat"])
            token_id = payload["jti"]
            expiry_raw = payload.get("exp")
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidToken("token claims are invalid") from exc

        if issuer != self._issuer:
            raise InvalidToken("token issuer is invalid")
        if not all(isinstance(value, str) and value for value in (subject, username, token_id)):
            raise InvalidToken("token identity claims are invalid")

        now_timestamp = int(self._clock.now().timestamp())
        if issued_timestamp > now_timestamp + 60:
            raise InvalidToken("token issue time is in the future")

        expires_at: datetime | None = None
        if expiry_raw is not None:
            try:
                expiry_timestamp = int(expiry_raw)
            except (TypeError, ValueError) as exc:
                raise InvalidToken("token claims are invalid") from exc
            if expiry_timestamp <= now_timestamp:
                raise InvalidToken("token has expired")
            if expiry_timestamp <= issued_timestamp:
                raise InvalidToken("token lifetime is invalid")
            expires_at = datetime.fromtimestamp(expiry_timestamp, tz=timezone.utc)

        return TokenClaims(
            subject=subject,
            username=username,
            role=role,
            issued_at=datetime.fromtimestamp(issued_timestamp, tz=timezone.utc),
            expires_at=expires_at,
            token_id=token_id,
        )
