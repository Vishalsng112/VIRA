"""Shared API dependencies: typed principals, admin gate, errors, correlation IDs."""
import uuid
from typing import Callable

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from vira import errors
from vira.auth import auth, database
from vira.auth.principals import DevicePrincipal, UserPrincipal


def correlation_id_of(request: Request) -> str:
    return getattr(request.state, "correlation_id", None) or str(uuid.uuid4())


def error_body(code: str, message, correlation_id: str) -> dict:
    # ``detail`` is kept for the existing web UI; ``error`` is the contract shape.
    return {"detail": message, "error": {"code": code, "message": message,
                                         "correlation_id": correlation_id}}


def install_error_handling(app: FastAPI) -> None:
    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next):
        # Generated server-side when absent; never treated as authentication.
        supplied = request.headers.get("X-Correlation-ID", "")
        request.state.correlation_id = supplied[:64] if supplied else str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        return response

    @app.exception_handler(errors.ViraError)
    async def vira_error_handler(request: Request, exc: errors.ViraError):
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, correlation_id_of(request)),
            headers=exc.headers,
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException):
        code = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
                409: "conflict", 429: "rate_limited"}.get(exc.status_code, "http_error")
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, exc.detail, correlation_id_of(request)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        fields = [".".join(str(p) for p in e.get("loc", ())[1:]) or "body" for e in exc.errors()]
        return JSONResponse(
            status_code=422,
            content=error_body("validation_failed",
                               "Invalid request: " + ", ".join(sorted(set(fields))),
                               correlation_id_of(request)),
        )


def build_auth_dependencies(kernel) -> dict:
    """Return the FastAPI dependencies bound to a kernel instance."""

    def _session_token(request: Request):
        authorization = request.headers.get("Authorization", "")
        bearer = authorization[7:].strip() if authorization.startswith("Bearer ") else None
        if bearer and bearer.startswith("vdc_"):
            # A device credential is never a user session (no impersonation).
            return None, True
        return bearer or request.session.get("session_id"), False

    def get_current_user(request: Request) -> UserPrincipal:
        token, device_credential = _session_token(request)
        principal = None if device_credential else auth.resolve_principal(token)
        if not principal:
            database.record_auth_audit(
                "authentication", "request.authenticate", False, session_id=token,
                resource=request.url.path, correlation_id=correlation_id_of(request),
                details="device credential on user endpoint" if device_credential else None,
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        return principal

    def require_admin(principal: UserPrincipal = Depends(get_current_user)) -> UserPrincipal:
        if not principal.is_admin:
            raise errors.Forbidden("Administrator role required", code="admin_required")
        return principal

    def get_device_principal(request: Request) -> DevicePrincipal:
        authorization = request.headers.get("Authorization", "")
        token = authorization[7:].strip() if authorization.startswith("Bearer ") else \
            request.headers.get("X-Device-Credential")
        # Cookie sessions are intentionally ignored here: a user session alone
        # can never act as a device.
        return kernel.device_service.authenticate_credential(token)

    return {
        "get_current_user": get_current_user,
        "require_admin": require_admin,
        "get_device_principal": get_device_principal,
    }
