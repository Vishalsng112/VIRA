"""HTTP security headers and cookie-session CSRF origin checks."""
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
_CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "font-src 'self' data:; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "same-origin")
        headers.setdefault("Content-Security-Policy", _CSP)
        headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        forwarded = request.headers.get("x-forwarded-proto", "").lower()
        if request.url.scheme == "https" or forwarded.startswith("https"):
            headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response


def _netloc(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    try:
        return urlsplit(raw).netloc.lower()
    except ValueError:
        return ""


class OriginProtectionMiddleware(BaseHTTPMiddleware):
    """Reject cross-site cookie-authenticated state changes.

    Bearer/device API clients do not use cookies and are unaffected. Browsers
    normally send Origin on POST/PATCH/DELETE; a missing Origin is allowed for
    command-line clients, while an explicit cross-site Origin is rejected.
    """

    def __init__(
        self,
        app,
        *,
        session_cookie: str = "vira_session",
        allowed_origins: tuple[str, ...] = (),
    ) -> None:
        super().__init__(app)
        self.session_cookie = session_cookie
        self.allowed = {_netloc(item) for item in allowed_origins if _netloc(item)}

    async def dispatch(self, request, call_next):
        if request.method in _SAFE_METHODS or not request.cookies.get(self.session_cookie):
            return await call_next(request)

        origin = request.headers.get("origin") or request.headers.get("referer")
        if not origin:
            if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
                return self._reject(request)
            return await call_next(request)

        origin_host = _netloc(origin)
        request_host = _netloc(request.headers.get("host", ""))
        if origin_host and (origin_host == request_host or origin_host in self.allowed):
            return await call_next(request)
        return self._reject(request)

    @staticmethod
    def _reject(request):
        return JSONResponse(
            status_code=403,
            content={
                "detail": "Cross-site request blocked.",
                "error": {
                    "code": "csrf_blocked",
                    "message": "Cross-site request blocked.",
                    "correlation_id": getattr(request.state, "correlation_id", None),
                },
            },
        )
