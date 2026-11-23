"""Sanitized failures exposed by the Quick Lab HTTP adapter."""

from __future__ import annotations

from xiaoying_quick.modules.labs import LabContractErrorCode
from xiaoying_quick.shared.compat import StrEnum


class LabHttpErrorCode(StrEnum):
    CLOSED = "closed"
    INVALID_REQUEST = "invalid_request"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    HTTP_CLIENT_ERROR = "http_client_error"
    RATE_LIMITED = "rate_limited"
    HTTP_SERVER_ERROR = "http_server_error"
    UNEXPECTED_STATUS = "unexpected_status"
    RESPONSE_TOO_LARGE = "response_too_large"
    INVALID_JSON = "invalid_json"
    INVALID_RESPONSE = "invalid_response"


class LabHttpError(RuntimeError):
    """A safe-to-report Lab failure with no raw response or secret attached."""

    def __init__(
        self,
        code: LabHttpErrorCode,
        *,
        request_id: str,
        retryable: bool,
        status_code: int | None = None,
        contract_code: LabContractErrorCode | None = None,
    ) -> None:
        super().__init__(f"Lab HTTP request failed: {code.value} (request_id={request_id})")
        self.code = code
        self.request_id = request_id
        self.retryable = retryable
        self.status_code = status_code
        self.contract_code = contract_code
