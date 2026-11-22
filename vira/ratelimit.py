"""Request rate limiting for public and authenticated VIRA endpoints."""
import hashlib
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


@dataclass(frozen=True)
class RateLimitRule:
    limit: int
    window_seconds: float


DEFAULT_RULES = {
    "/api/v1/auth/login": RateLimitRule(10, 60),
    "/api/v1/devices/pairing-code": RateLimitRule(10, 60),
    "/api/v1/access/cloudflare/connect": RateLimitRule(10, 300),
    "/api/v1/access/tailscale/connect": RateLimitRule(10, 300),
    "/api/v1/auth/setup": RateLimitRule(5, 300),
    "/api/v1/auth/password/reset": RateLimitRule(5, 300),
    "/chat": RateLimitRule(30, 60),
    "/api/v1/conversations": RateLimitRule(60, 60),
    "/api/v1/devices/pair": RateLimitRule(5, 60),
    "/api/v1/insights": RateLimitRule(120, 60),
    "/api/v1/rag": RateLimitRule(60, 60),
    "/api/v1/workflows": RateLimitRule(60, 60),
    "/api/v1/account": RateLimitRule(10, 60),
    "/api/v1/admin": RateLimitRule(300, 60),
    "/agents": RateLimitRule(120, 60),
    "/tools": RateLimitRule(120, 60),
}


@dataclass
class _Window:
    count: int = 1
    reset_at: float = field(default_factory=time.monotonic)


class RateLimiter:
    def __init__(self, rules: Optional[Dict[str, RateLimitRule]] = None):
        self.rules = dict(rules or DEFAULT_RULES)
        self._windows: Dict[str, _Window] = {}

    def rule_for(self, path: str) -> Optional[RateLimitRule]:
        for prefix, rule in self.rules.items():
            if path.startswith(prefix):
                return rule
        return None

    def check(self, key: str, rule: RateLimitRule) -> Tuple[bool, float]:
        now = time.monotonic()
        window = self._windows.get(key)
        if window is None or now >= window.reset_at:
            self._windows[key] = _Window(count=1, reset_at=now + rule.window_seconds)
            return True, 0
        if window.count < rule.limit:
            window.count += 1
            return True, 0
        return False, max(0.0, window.reset_at - now)

    def prune(self, max_entries: int = 10000) -> None:
        if len(self._windows) <= max_entries:
            return
        now = time.monotonic()
        for key in [key for key, window in self._windows.items() if now >= window.reset_at]:
            self._windows.pop(key, None)


def client_ip(request: Request) -> str:
    """Return the real client IP when cloudflared is the local proxy.

    Cloudflare sets CF-Connecting-IP. It is trusted only when the TCP peer is
    loopback, which is how a local cloudflared service connects. Direct clients
    cannot spoof it to escape rate limits.
    """
    peer = request.client.host if request.client else ""
    if peer in ("127.0.0.1", "::1"):
        candidate = (request.headers.get("cf-connecting-ip") or "").strip()
        if candidate:
            return candidate
        forwarded = (request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded
    return peer or "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: Optional[RateLimiter] = None, enabled: bool = True):
        super().__init__(app)
        self.limiter = limiter or RateLimiter()
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)
        rule = self.limiter.rule_for(request.url.path)
        if rule is None:
            return await call_next(request)
        credential = (
            request.headers.get("authorization")
            or request.cookies.get("vira_session")
        )
        identity = (
            hashlib.sha256(credential.encode("utf-8")).hexdigest()[:32]
            if credential
            else client_ip(request)
        )
        key = f"{request.url.path}:{identity[:80]}"
        allowed, retry_after = self.limiter.check(key, rule)
        if not allowed:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(max(1, int(retry_after)))},
                content={
                    "detail": "Too many requests",
                    "error": {
                        "code": "rate_limited",
                        "message": "Too many requests; retry shortly.",
                        "correlation_id": getattr(request.state, "correlation_id", None),
                    },
                },
            )
        self.limiter.prune()
        return await call_next(request)
