"""Application errors with stable machine-readable codes (design section 7.6/9.5).

Services raise these; the API layer maps them to HTTP responses of the shape
``{"detail": <message>, "error": {"code", "message", "correlation_id"}}``.
The message must be safe to show to a client: never include secrets, hashes
or other users' data.
"""
from typing import Optional


class ViraError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str = "", code: Optional[str] = None, headers: Optional[dict] = None):
        super().__init__(message or self.code)
        self.message = message or self.code
        if code:
            self.code = code
        self.headers = headers or {}


class ValidationFailed(ViraError):
    status_code = 422
    code = "validation_failed"


class BadRequest(ViraError):
    status_code = 400
    code = "bad_request"


class Unauthorized(ViraError):
    status_code = 401
    code = "unauthorized"


class Forbidden(ViraError):
    status_code = 403
    code = "forbidden"


class NotFound(ViraError):
    status_code = 404
    code = "not_found"


class Conflict(ViraError):
    status_code = 409
    code = "conflict"


class PayloadTooLarge(ViraError):
    status_code = 413
    code = "payload_too_large"


class RateLimited(ViraError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, message: str = "Rate limit exceeded", retry_after: float = 1.0):
        super().__init__(message, headers={"Retry-After": str(max(1, int(retry_after + 0.999)))})
        self.retry_after = retry_after
