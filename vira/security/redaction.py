"""Redaction helpers for audit exports, approvals and logs.

The goal is not to make a value cryptographically unrecoverable; it is to stop
secrets from being copied into places an administrator (or a support bundle)
might share. Keys are matched case-insensitively and string patterns cover the
common token shapes.
"""
from __future__ import annotations

import json
import re
from typing import Any

REDACTED = "[REDACTED]"

_SECRET_KEY = re.compile(
    r"(pass(word)?|secret|token|api[_-]?key|apikey|authorization|cookie|"
    r"credential|private[_-]?key|recovery[_-]?code|session[_-]?id|"
    r"bearer|client[_-]?secret|database[_-]?url|dsn)",
    re.IGNORECASE,
)
_VALUE_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(r"""(?i)\b(password|token|secret|api[_-]?key)["']?\s*[:=]\s*["']?[^\s,;}"']+"""),
]


def _redact_string(value: str) -> str:
    stripped = value.strip()
    if stripped[:1] in ("{", "["):
        try:
            parsed = json.loads(stripped)
        except (TypeError, ValueError):
            parsed = None
        if parsed is not None:
            return json.dumps(redact(parsed), default=str, ensure_ascii=False)
    result = value
    for pattern in _VALUE_PATTERNS:
        result = pattern.sub(REDACTED, result)
    return result


def redact(value: Any, depth: int = 0) -> Any:
    """Recursively redact secret-looking keys and token-shaped strings."""
    if depth > 8:
        return REDACTED
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if _SECRET_KEY.search(str(key)):
                result[key] = REDACTED
            else:
                result[key] = redact(item, depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        return [redact(item, depth + 1) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value
