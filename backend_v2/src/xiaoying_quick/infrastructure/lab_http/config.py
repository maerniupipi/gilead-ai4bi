"""Validated configuration for the real Quick Lab HTTP boundary."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from urllib.parse import urlsplit

_LAB_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")


@dataclass(frozen=True)
class LabHttpConfig:
    """Connection settings injected by the composition root.

    The token is excluded from ``repr`` so routine diagnostics cannot disclose
    it. Query strings and URL user-info are rejected because both are commonly
    copied into access logs.
    """

    endpoint_url: str
    lab_tokens: Mapping[str, str] = field(repr=False)
    timeout_seconds: float
    max_response_bytes: int = 1_000_000
    allow_insecure_http: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint_url, str) or not self.endpoint_url.strip():
            raise ValueError("Lab endpoint_url must not be empty")
        endpoint_url = self.endpoint_url.strip().rstrip("/")
        try:
            parts = urlsplit(endpoint_url)
            hostname = parts.hostname
        except ValueError as error:
            raise ValueError("Lab endpoint_url is invalid") from error
        if parts.scheme not in {"http", "https"} or not parts.netloc or not hostname:
            raise ValueError("Lab endpoint_url must be an absolute HTTP URL")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("Lab endpoint_url must not contain credentials, query, or fragment")
        if parts.scheme == "http" and not self.allow_insecure_http:
            raise ValueError("Lab endpoint_url must use HTTPS")
        if not parts.path.endswith("/opentrek-chat/v2/completions"):
            raise ValueError(
                "Lab endpoint_url must be the complete opentrek-chat v2 completions URL"
            )

        if not isinstance(self.lab_tokens, Mapping) or not self.lab_tokens:
            raise ValueError("Lab token mapping must not be empty")
        clean_tokens: dict[str, str] = {}
        for lab_id, token in self.lab_tokens.items():
            if not isinstance(lab_id, str) or not _LAB_ID_PATTERN.fullmatch(lab_id):
                raise ValueError("Lab token mapping contains an invalid lab_id")
            if not isinstance(token, str) or not token:
                raise ValueError("Lab token mapping contains an empty token")
            if token != token.strip() or not all(
                0x21 <= ord(character) <= 0x7E for character in token
            ):
                raise ValueError("Lab token contains invalid header characters")
            clean_tokens[lab_id] = token

        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("Lab timeout_seconds must be a positive finite number")
        if (
            isinstance(self.max_response_bytes, bool)
            or not isinstance(self.max_response_bytes, int)
            or self.max_response_bytes <= 0
        ):
            raise ValueError("Lab max_response_bytes must be a positive integer")

        object.__setattr__(self, "endpoint_url", endpoint_url)
        object.__setattr__(self, "lab_tokens", MappingProxyType(clean_tokens))
        object.__setattr__(self, "timeout_seconds", float(self.timeout_seconds))

    def token_for(self, lab_id: str) -> str:
        if not isinstance(lab_id, str) or not _LAB_ID_PATTERN.fullmatch(lab_id):
            raise ValueError("lab_id is invalid")
        token = self.lab_tokens.get(lab_id)
        if token is None:
            raise ValueError("No Lab token is configured for lab_id")
        return token
