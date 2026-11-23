"""Validated connection settings for the OpenAI-protocol chat endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

#: How the model should spend its deliberation budget.
#:
#: ``auto`` sends nothing and lets the model decide — the only safe value for an
#: endpoint that does not understand the flag. ``off`` is measurably cheaper on
#: deepseek-v4-flash (a short routing call drops 1.7s → 0.5s and stops charging
#: reasoning tokens against ``max_tokens``); whether it is *good enough* is a
#: question for the eval set, not for this file.
ReasoningMode = Literal["auto", "on", "off"]

_THINKING_FLAG: dict[str, dict[str, str]] = {
    "on": {"type": "enabled"},
    "off": {"type": "disabled"},
}


@dataclass(frozen=True)
class LlmConfig:
    """Where the model lives and how much of its answer we are willing to read."""

    endpoint_url: str
    api_key: str
    model_id: str
    timeout_seconds: float = 60.0
    max_response_bytes: int = 2_000_000
    temperature: float = 0.0
    max_tokens: int = 16_384
    reasoning: ReasoningMode = "auto"
    #: Explicit per-run thinking control (OpenAI-compatible endpoints such as
    #: qwen3 take ``enable_thinking``/``thinking_budget``). ``None`` means
    #: "no explicit choice" and the record's ``reasoning`` flag applies.
    enable_thinking: bool | None = None
    thinking_budget: int | None = None

    @property
    def request_overrides(self) -> dict[str, Any]:
        """Extra request fields this configuration implies, if any."""

        if self.enable_thinking is not None:
            overrides: dict[str, Any] = {"enable_thinking": self.enable_thinking}
            if self.enable_thinking and self.thinking_budget:
                overrides["thinking_budget"] = self.thinking_budget
            return overrides
        flag = _THINKING_FLAG.get(self.reasoning)
        return {"thinking": flag} if flag is not None else {}

    def __post_init__(self) -> None:
        self._validate_endpoint(self.endpoint_url)
        token = self.api_key
        if not token or token != token.strip():
            raise ValueError("model api key must not be blank or padded")
        if not all(0x21 <= ord(character) <= 0x7E for character in token):
            raise ValueError("model api key contains invalid header characters")
        if not self.model_id.strip():
            raise ValueError("model id must not be blank")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 300:
            raise ValueError("model timeout must be within (0, 300] seconds")
        if self.max_response_bytes < 1_024:
            raise ValueError("model max response bytes must be at least 1 KiB")
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError("model temperature must be within [0, 2]")
        if self.max_tokens < 2_048:
            # A reasoning model spends this budget on deliberation before it
            # answers; a small ceiling silently truncates to nothing.
            raise ValueError("model max tokens must be at least 2048")
        if self.reasoning not in {"auto", "on", "off"}:
            raise ValueError("model reasoning mode must be auto, on, or off")
        if self.thinking_budget is not None and not 1 <= self.thinking_budget <= 200_000:
            raise ValueError("thinking budget must be within [1, 200000]")

    @staticmethod
    def _validate_endpoint(endpoint_url: str) -> None:
        try:
            parts = urlsplit(endpoint_url)
            hostname = parts.hostname
        except ValueError as error:
            raise ValueError("model endpoint url is invalid") from error
        if not parts.netloc or not hostname:
            raise ValueError("model endpoint url must be absolute")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("model endpoint url must not carry credentials, query, or fragment")
        if parts.scheme == "http":
            if hostname not in _LOCAL_HOSTS:
                raise ValueError("plain http model endpoints are only allowed on localhost")
        elif parts.scheme != "https":
            raise ValueError("model endpoint url must use https")
        if not parts.path.rstrip("/").endswith("/chat/completions"):
            raise ValueError("model endpoint url must be the complete /chat/completions url")


__all__ = ["LlmConfig", "ReasoningMode"]
