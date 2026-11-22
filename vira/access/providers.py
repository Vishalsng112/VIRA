"""Built-in access providers.

The request provider keeps the existing dashboard-derived address working.
The custom provider covers an intentionally configured URL (for example a
Cloudflare named tunnel). The Tailscale provider discovers the private
MagicDNS name or tailnet address and never publishes a Funnel route.
"""
import json
import shutil
import subprocess
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse

from starlette.requests import Request

from .base import AccessEndpoint


def normalize_url(value: Any) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = f"http://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return raw.rstrip("/")


class RequestProvider:
    """Use the address the dashboard request arrived on."""

    kind = "request"
    label = "Dashboard address"

    def status(self, request: Request, settings: Dict[str, Any]) -> Dict[str, Any]:
        url = normalize_url(str(request.base_url))
        if not url:
            return {
                "kind": self.kind,
                "label": self.label,
                "available": False,
                "reason": "The dashboard request has no usable base URL.",
                "endpoint": None,
            }
        return {
            "kind": self.kind,
            "label": self.label,
            "available": True,
            "reason": None,
            "endpoint": AccessEndpoint(
                kind=self.kind,
                url=url,
                label=self.label,
                detail="Address used to open the dashboard",
            ),
        }


class CustomProvider:
    """Use an explicitly configured reachable URL."""

    kind = "custom"
    label = "Configured URL"

    def status(self, request: Request, settings: Dict[str, Any]) -> Dict[str, Any]:
        url = normalize_url(settings.get("public_url"))
        if not url:
            return {
                "kind": self.kind,
                "label": self.label,
                "available": False,
                "reason": "Set access.public_url to use a custom address.",
                "endpoint": None,
            }
        return {
            "kind": self.kind,
            "label": self.label,
            "available": True,
            "reason": None,
            "endpoint": AccessEndpoint(
                kind=self.kind,
                url=url,
                label=self.label,
                detail="access.public_url",
            ),
        }


class TailscaleProvider:
    """Discover the private Tailscale address of this machine."""

    kind = "tailscale"
    label = "Tailscale private"

    def __init__(
        self,
        runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
        which: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        self._runner = runner or subprocess.run
        self._which = which or shutil.which

    def _status_json(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        binary = str(settings.get("binary") or "tailscale")
        if not self._which(binary):
            raise RuntimeError(
                "Tailscale CLI not found. Install Tailscale and run `tailscale up`."
            )
        timeout = float(settings.get("timeout_seconds", 2) or 2)
        try:
            result = self._runner(
                [binary, "status", "--json"],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"Could not run Tailscale: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or "").strip() or f"exit code {result.returncode}"
            raise RuntimeError(f"Tailscale status failed: {detail}")
        try:
            return json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError("Tailscale returned invalid status JSON.") from exc

    def status(self, request: Request, settings: Dict[str, Any]) -> Dict[str, Any]:
        try:
            data = self._status_json(settings)
        except RuntimeError as exc:
            return {
                "kind": self.kind,
                "label": self.label,
                "available": False,
                "reason": str(exc),
                "endpoint": None,
            }

        state = str(data.get("BackendState") or "").strip()
        if state != "Running":
            shown = state.lower() or "not running"
            return {
                "kind": self.kind,
                "label": self.label,
                "available": False,
                "reason": f"Tailscale is {shown}. Run `tailscale up`.",
                "endpoint": None,
            }

        self_info = data.get("Self") or {}
        dns_name = str(self_info.get("DNSName") or "").rstrip(".")
        raw_ips = self_info.get("TailscaleIPs") or []
        ips = [str(ip) for ip in raw_ips if str(ip).strip()]
        ipv4 = next((ip for ip in ips if ":" not in ip), None)
        prefer_dns = bool(settings.get("prefer_dns_name", True))
        host = dns_name if prefer_dns and dns_name else (ipv4 or (ips[0] if ips else ""))
        if not host:
            return {
                "kind": self.kind,
                "label": self.label,
                "available": False,
                "reason": "Tailscale is connected but has no tailnet address yet.",
                "endpoint": None,
            }

        scheme = str(settings.get("scheme") or "http").strip().lower()
        if scheme not in ("http", "https"):
            scheme = "http"
        try:
            port = int(settings.get("port", 8000))
        except (TypeError, ValueError):
            port = 8000
        if port < 1 or port > 65535:
            port = 8000
        default_port = 443 if scheme == "https" else 80
        netloc = host if port == default_port else f"{host}:{port}"
        url = f"{scheme}://{netloc}"

        tailnet = data.get("CurrentTailnet") or {}
        tailnet_name = str(tailnet.get("Name") or tailnet.get("MagicDNSSuffix") or "").strip()
        detail = "Private tailnet"
        if tailnet_name:
            detail = f"Private tailnet · {tailnet_name}"

        return {
            "kind": self.kind,
            "label": self.label,
            "available": True,
            "reason": None,
            "endpoint": AccessEndpoint(
                kind=self.kind,
                url=url,
                label=self.label,
                detail=detail,
            ),
            "host": host,
            "tailnet": tailnet_name or None,
        }
