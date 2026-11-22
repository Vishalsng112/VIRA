"""Pluggable server access addresses.

VIRA never assumes the address a browser used is reachable by other devices.
An access provider resolves the address that pairing and clients should use.
Tailscale is the first built-in provider; add another provider here without
changing the pairing API or the clients.
"""
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

from starlette.requests import Request


@dataclass(frozen=True)
class AccessEndpoint:
    """A URL a client can use to reach this server."""

    kind: str
    url: str
    label: str
    detail: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "url": self.url,
            "label": self.label,
            "detail": self.detail,
        }


class AccessProvider(Protocol):
    """One source of reachable server addresses."""

    kind: str
    label: str

    def status(self, request: Request, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Return availability plus an optional ``AccessEndpoint``."""
        ...


@dataclass
class AccessResolution:
    provider: str
    endpoint: AccessEndpoint
    candidates: list[AccessEndpoint]
    warnings: list[str]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "endpoint": self.endpoint.as_dict(),
            "candidates": [item.as_dict() for item in self.candidates],
            "warnings": list(self.warnings),
        }
