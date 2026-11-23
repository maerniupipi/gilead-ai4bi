"""Transport-independent application errors."""

from __future__ import annotations


class ApplicationError(Exception):
    code = "APPLICATION_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AuthenticationFailed(ApplicationError):
    code = "AUTHENTICATION_FAILED"


class InvalidToken(AuthenticationFailed):
    code = "INVALID_TOKEN"


class Forbidden(ApplicationError):
    code = "FORBIDDEN"


class NotFound(ApplicationError):
    code = "NOT_FOUND"


class Conflict(ApplicationError):
    code = "CONFLICT"


class ValidationFailed(ApplicationError):
    code = "VALIDATION_FAILED"


class InvalidTransition(Conflict):
    code = "INVALID_TRANSITION"
