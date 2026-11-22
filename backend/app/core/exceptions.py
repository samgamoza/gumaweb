"""Domain/application exceptions, mapped to HTTP responses in app.main."""

from __future__ import annotations


class GumaWebError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFoundError(GumaWebError):
    status_code = 404
    code = "not_found"


class ConflictError(GumaWebError):
    status_code = 409
    code = "conflict"


class ValidationFailedError(GumaWebError):
    status_code = 422
    code = "validation_failed"


class AuthenticationError(GumaWebError):
    status_code = 401
    code = "unauthenticated"


class PermissionDeniedError(GumaWebError):
    status_code = 403
    code = "forbidden"


class RateLimitedError(GumaWebError):
    status_code = 429
    code = "rate_limited"
