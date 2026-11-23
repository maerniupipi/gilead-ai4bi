"""Typed failures raised by the chat completion adapter."""

from __future__ import annotations

from xiaoying_quick.shared.compat import StrEnum


class LlmErrorCode(StrEnum):
    NOT_CONFIGURED = "not_configured"
    INVALID_REQUEST = "invalid_request"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    RATE_LIMITED = "rate_limited"
    HTTP_CLIENT_ERROR = "http_client_error"
    HTTP_SERVER_ERROR = "http_server_error"
    UNEXPECTED_STATUS = "unexpected_status"
    RESPONSE_TOO_LARGE = "response_too_large"
    INVALID_JSON = "invalid_json"
    EMPTY_COMPLETION = "empty_completion"
    TRUNCATED = "truncated"
    INVALID_PAYLOAD = "invalid_payload"
    CLOSED = "closed"


class LlmError(RuntimeError):
    """Model call failed.

    There is no silent degradation anywhere in the pipeline: a failed model
    call surfaces as a run failure so the cause is visible during debugging
    instead of being masked by a deterministic stand-in.
    """

    def __init__(
        self,
        code: LlmErrorCode,
        *,
        purpose: str,
        request_id: str,
        retryable: bool = False,
        status_code: int | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(f"llm {purpose} failed: {code.value}")
        self.code = code
        self.purpose = purpose
        self.request_id = request_id
        self.retryable = retryable
        self.status_code = status_code
        self.detail = detail


__all__ = ["LlmError", "LlmErrorCode"]
