"""Access providers for reachable server addresses."""
from .base import AccessEndpoint, AccessProvider, AccessResolution
from .providers import (
    CloudflareProvider,
    CustomProvider,
    LanProvider,
    RequestProvider,
    TailscaleProvider,
)
from .resolver import AccessResolver, access_status, resolve_access

__all__ = [
    "AccessEndpoint",
    "AccessProvider",
    "AccessResolution",
    "AccessResolver",
    "CloudflareProvider",
    "CustomProvider",
    "LanProvider",
    "RequestProvider",
    "TailscaleProvider",
    "access_status",
    "resolve_access",
]
