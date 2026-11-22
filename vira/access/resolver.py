"""Resolve the address clients and pairing codes should use."""
from typing import Any, Dict, Iterable, Optional

from starlette.requests import Request

from .base import AccessEndpoint, AccessProvider, AccessResolution
from .providers import (
    CloudflareProvider,
    CustomProvider,
    LanProvider,
    RequestProvider,
    TailscaleProvider,
)


class AccessResolver:
    """Selects a provider while keeping every candidate available for clients."""

    def __init__(self, providers: Optional[Iterable[AccessProvider]] = None) -> None:
        self.providers: list[AccessProvider] = list(
            providers or (
                RequestProvider(),
                LanProvider(),
                CloudflareProvider(),
                CustomProvider(),
                TailscaleProvider(),
            )
        )

    def register(self, provider: AccessProvider) -> "AccessResolver":
        """Add a provider without changing pairing or client code."""
        self.providers.append(provider)
        return self

    @staticmethod
    def _settings_for(provider: AccessProvider, settings: Dict[str, Any]) -> Dict[str, Any]:
        nested = settings.get(provider.kind)
        if isinstance(nested, dict):
            return nested
        return settings

    def _entries(self, request: Request, settings: Dict[str, Any]) -> list[Dict[str, Any]]:
        entries: list[Dict[str, Any]] = []
        for provider in self.providers:
            provider_settings = self._settings_for(provider, settings)
            if provider.kind == "tailscale" and provider_settings.get("enabled", True) is False:
                entries.append({
                    "kind": provider.kind,
                    "label": provider.label,
                    "available": False,
                    "reason": "Tailscale provider is disabled in access.tailscale.enabled.",
                    "endpoint": None,
                })
                continue
            try:
                entry = provider.status(request, provider_settings)
            except Exception as exc:  # a provider must never break pairing
                entry = {
                    "kind": provider.kind,
                    "label": provider.label,
                    "available": False,
                    "reason": f"Provider error: {exc}",
                    "endpoint": None,
                }
            endpoint = entry.get("endpoint")
            if endpoint is not None and not isinstance(endpoint, AccessEndpoint):
                entry["endpoint"] = None
            entries.append(entry)
        return entries

    @staticmethod
    def _endpoint(entries: list[Dict[str, Any]], kind: str) -> Optional[AccessEndpoint]:
        for entry in entries:
            if entry.get("kind") == kind:
                return entry.get("endpoint")
        return None

    @staticmethod
    def _reason(entries: list[Dict[str, Any]], kind: str) -> str:
        for entry in entries:
            if entry.get("kind") == kind:
                return str(entry.get("reason") or "").strip()
        return ""

    def _select(
        self,
        mode: str,
        entries: list[Dict[str, Any]],
        settings: Dict[str, Any],
    ) -> tuple[AccessEndpoint, list[AccessEndpoint], list[str]]:
        request = self._endpoint(entries, "request")
        lan = self._endpoint(entries, "lan")
        cloudflare = self._endpoint(entries, "cloudflare")
        custom = self._endpoint(entries, "custom")
        tailscale = self._endpoint(entries, "tailscale")
        warnings: list[str] = []

        if mode == "request":
            primary = request
        elif mode == "lan":
            primary = lan
            if not primary:
                reason = self._reason(entries, "lan") or "No LAN address is available."
                warnings.append(f"{reason} Pairing uses the dashboard address.")
        elif mode == "cloudflare":
            primary = cloudflare or lan
            if not cloudflare:
                reason = self._reason(entries, "cloudflare") or "Cloudflare is not configured."
                warnings.append(f"{reason} Pairing uses the local network address.")
        elif mode == "custom":
            primary = custom
            if not primary:
                warnings.append(
                    "No valid custom URL is configured. Pairing uses the dashboard address."
                )
        elif mode == "tailscale":
            primary = tailscale
            if not primary:
                reason = self._reason(entries, "tailscale") or "Tailscale is not connected."
                warnings.append(f"{reason} Pairing uses the dashboard address.")
        elif mode == "auto":
            if custom:
                primary = custom
            elif cloudflare:
                primary = cloudflare
            elif lan:
                primary = lan
            elif tailscale:
                primary = tailscale
            else:
                primary = request
                ts_settings = settings.get("tailscale")
                enabled = not isinstance(ts_settings, dict) or ts_settings.get("enabled", True) is not False
                if enabled:
                    reason = self._reason(entries, "tailscale") or "Tailscale is not connected."
                    warnings.append(
                        f"{reason} Pairing uses the address you opened the dashboard with."
                    )
        else:
            primary = request
            warnings.append(
                f"Unknown access provider '{mode}'. Pairing uses the dashboard address."
            )

        primary = primary or request
        if primary is None:
            raise RuntimeError("No access provider returned a usable address.")

        ordered: list[AccessEndpoint] = []
        seen: set[str] = set()
        for item in (primary, cloudflare, lan, tailscale, custom, request):
            if item is None or item.url in seen:
                continue
            ordered.append(item)
            seen.add(item.url)
        return primary, ordered, warnings

    def resolve(self, request: Request, config: Dict[str, Any]) -> AccessResolution:
        settings = config.get("access") or {}
        mode = str(settings.get("provider") or "auto").strip().lower()
        entries = self._entries(request, settings)
        primary, candidates, warnings = self._select(mode, entries, settings)
        return AccessResolution(
            provider=primary.kind,
            endpoint=primary,
            candidates=candidates,
            warnings=warnings,
        )

    def status(self, request: Request, config: Dict[str, Any]) -> Dict[str, Any]:
        settings = config.get("access") or {}
        mode = str(settings.get("provider") or "auto").strip().lower()
        entries = self._entries(request, settings)
        primary, candidates, warnings = self._select(mode, entries, settings)
        serialized = []
        for entry in entries:
            endpoint = entry.get("endpoint")
            serialized.append({
                "kind": entry.get("kind"),
                "label": entry.get("label"),
                "available": bool(entry.get("available")),
                "reason": entry.get("reason"),
                "endpoint": endpoint.as_dict() if isinstance(endpoint, AccessEndpoint) else None,
                "host": entry.get("host"),
                "tailnet": entry.get("tailnet"),
            })
        return {
            "mode": mode,
            "resolved": primary.as_dict(),
            "candidates": [item.as_dict() for item in candidates],
            "warnings": warnings,
            "providers": serialized,
        }


_default_resolver = AccessResolver()


def resolve_access(request: Request, config: Dict[str, Any]) -> AccessResolution:
    return _default_resolver.resolve(request, config)


def access_status(request: Request, config: Dict[str, Any]) -> Dict[str, Any]:
    return _default_resolver.status(request, config)
