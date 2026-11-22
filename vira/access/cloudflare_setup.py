"""Guided Cloudflare named-tunnel setup.

Two paths are supported:

* an existing cloudflared service (for example a token-managed tunnel) only
  needs the public hostname so VIRA can save and verify it;
* otherwise VIRA starts `cloudflared tunnel login`, creates or reuses the named
  tunnel, routes DNS and starts a managed tunnel process.

Cloudflare account login and DNS/zone ownership are still completed by the user
in Cloudflare's browser flow.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Optional

from .qr import qr_svg_data_uri

_HOSTNAME = re.compile(
    r"^(?=.{1,253}$)([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$"
)
_LOGIN_URL = re.compile(r"https://dash\.cloudflare\.com/argotunnel\?[^\s\"']+")
_TUNNEL_ID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")


def _install_command() -> str:
    if sys.platform.startswith("linux"):
        return (
            "curl -L --output cloudflared.deb "
            "https://github.com/cloudflare/cloudflared/releases/latest/download/"
            "cloudflared-linux-amd64.deb && sudo dpkg -i cloudflared.deb"
        )
    if sys.platform == "darwin":
        return "brew install cloudflared"
    if os.name == "nt":
        return "winget install Cloudflare.cloudflared"
    return "Install cloudflared from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"


class CloudflareController:
    def __init__(
        self,
        which: Optional[Callable[[str], Optional[str]]] = None,
        runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
        popen: Optional[Callable[..., subprocess.Popen]] = None,
        health_check: Optional[Callable[[str], bool]] = None,
        systemctl: Optional[Callable[[str], bool]] = None,
        data_dir: Optional[Path] = None,
    ) -> None:
        self._which = which or shutil.which
        self._runner = runner or subprocess.run
        self._popen = popen or subprocess.Popen
        self._health = health_check or self._default_health
        self._systemctl = systemctl or self._default_systemctl
        self._data_dir = data_dir or (Path("data") / "cloudflare")
        self._lock = threading.Lock()
        self._login_process: Optional[subprocess.Popen] = None
        self._tunnel_process: Optional[subprocess.Popen] = None
        self._auth_url: Optional[str] = None
        self._output: Deque[str] = deque(maxlen=30)
        self._last_error: Optional[str] = None

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _settings(config: Dict[str, Any]) -> Dict[str, Any]:
        access = config.get("access") or {}
        return access.get("cloudflare") or {}

    def _binary(self, settings: Dict[str, Any]) -> str:
        return str(settings.get("binary") or "cloudflared")

    def _dirs(self) -> tuple[Path, Path, Path]:
        root = self._data_dir
        cert = root / "cert.pem"
        return root, cert, root / "config.yml"

    def _env(self) -> Dict[str, str]:
        env = dict(os.environ)
        root, cert, _ = self._dirs()
        root.mkdir(parents=True, exist_ok=True)
        env["TUNNEL_ORIGIN_CERT"] = str(cert.resolve())
        return env

    def _set_error(self, value: str) -> None:
        with self._lock:
            self._last_error = value.strip()[:1200] or None

    def _clear_error(self) -> None:
        with self._lock:
            self._last_error = None

    def _process_alive(self, process: Optional[subprocess.Popen]) -> bool:
        return bool(process is not None and process.poll() is None)

    def _login_alive(self) -> bool:
        with self._lock:
            return self._process_alive(self._login_process)

    def _tunnel_alive(self) -> bool:
        with self._lock:
            return self._process_alive(self._tunnel_process)

    def _read_process(self, process: subprocess.Popen, *, login: bool) -> None:
        try:
            for line in process.stdout or []:
                text = str(line).strip()
                if not text:
                    continue
                with self._lock:
                    self._output.append(text)
                    match = _LOGIN_URL.search(text)
                    if match:
                        self._auth_url = match.group(0)
            code = process.wait()
            if code not in (0, None):
                with self._lock:
                    tail = "\n".join(self._output)
                    self._last_error = (tail or f"cloudflared exited with {code}")[-1200:]
        except Exception as exc:  # keep the dashboard usable
            self._set_error(f"cloudflared process failed: {exc}")
        finally:
            with self._lock:
                if login and self._login_process is process:
                    self._login_process = None
                if not login and self._tunnel_process is process:
                    self._tunnel_process = None

    def _default_systemctl(self, action: str) -> bool:
        try:
            result = self._runner(
                ["systemctl", action, "cloudflared"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def _default_health(self, url: str) -> bool:
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=6) as response:
                return response.status < 500
        except urllib.error.HTTPError as exc:
            # A login redirect or an Access challenge still proves the tunnel
            # reaches the origin. Cloudflare tunnel errors are 5xx.
            return exc.code < 500
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def _run(self, args: list[str], settings: Optional[Dict[str, Any]] = None,
             timeout: int = 45) -> subprocess.CompletedProcess:
        return self._runner(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=self._env(),
        )

    def _cert_exists(self) -> bool:
        _, cert, _ = self._dirs()
        return cert.exists()

    def _service_active(self) -> bool:
        return self._systemctl("is-active")

    def _public_url(self, settings: Dict[str, Any]) -> Optional[str]:
        raw = str(settings.get("public_url") or "").strip()
        if not raw:
            return None
        if "://" not in raw:
            raw = f"https://{raw}"
        if not raw.startswith("https://"):
            return None
        return raw.rstrip("/")

    def _next_steps(self, state: str, reason: str = "") -> list[str]:
        lowered = reason.lower()
        if state == "not_installed":
            return [
                "Install cloudflared on the machine that runs VIRA.",
                "Then click Refresh.",
            ]
        if state == "needs_login":
            return [
                "Open the Cloudflare login URL or scan the QR code.",
                "Choose the zone that owns the VIRA hostname.",
                "VIRA continues automatically after login.",
            ]
        if state == "needs_hostname":
            return [
                "Enter the public hostname you configured for this tunnel.",
                "It must be proxied through the same Cloudflare account.",
            ]
        if state == "stopped":
            return [
                "The named tunnel is configured but cloudflared is not running.",
                "Enter the hostname and start the tunnel again.",
            ]
        if "not reachable" in lowered:
            return [
                "Open the public hostname in a browser and check Cloudflare DNS.",
                "Confirm the tunnel routes that hostname to http://127.0.0.1:8000.",
                "If Cloudflare Access is enabled, the hostname may require a login.",
            ]
        if "permission" in lowered or "root" in lowered:
            return [
                "The VIRA service user cannot manage the cloudflared service.",
                "Run the tunnel install command once as root, or run VIRA as a user with permission.",
            ]
        return []

    def _payload(
        self,
        *,
        state: str,
        installed: bool,
        reason: Optional[str] = None,
        public_url: Optional[str] = None,
        hostname: Optional[str] = None,
        tunnel_name: Optional[str] = None,
        tunnel_id: Optional[str] = None,
        service_active: bool = False,
        logged_in: bool = False,
        login_in_progress: bool = False,
        tunnel_running: bool = False,
    ) -> Dict[str, Any]:
        auth_url = self._auth_url
        qr = None
        if auth_url:
            try:
                qr = qr_svg_data_uri(auth_url)
            except Exception:
                qr = None
        return {
            "state": state,
            "installed": installed,
            "connected": state == "running",
            "public_url": public_url,
            "hostname": hostname,
            "tunnel_name": tunnel_name,
            "tunnel_id": tunnel_id,
            "service_active": service_active,
            "logged_in": logged_in,
            "login_in_progress": login_in_progress,
            "tunnel_running": tunnel_running,
            "auth_url": auth_url,
            "auth_qr": qr,
            "reason": (reason or "").strip() or None,
            "next_steps": self._next_steps(state, reason or ""),
            "install_command": _install_command() if state == "not_installed" else None,
            "can_login": installed and not logged_in and not service_active,
            "provider": "cloudflare",
        }

    def status(self, config: Dict[str, Any]) -> Dict[str, Any]:
        settings = self._settings(config)
        binary = self._binary(settings)
        if not self._which(binary):
            return self._payload(state="not_installed", installed=False)

        service_active = self._service_active()
        logged_in = self._cert_exists()
        public_url = self._public_url(settings)
        hostname = str(settings.get("hostname") or "").strip() or None
        if public_url and not hostname:
            hostname = public_url.removeprefix("https://")
        tunnel_name = str(settings.get("tunnel_name") or "vira").strip()
        tunnel_id = str(settings.get("tunnel_id") or "").strip() or None
        login_in_progress = self._login_alive()
        tunnel_running = service_active or self._tunnel_alive()
        with self._lock:
            failure = self._last_error

        if public_url:
            if not (service_active or tunnel_running):
                return self._payload(
                    state="stopped",
                    installed=True,
                    reason="Cloudflare is configured but the tunnel process is not running.",
                    public_url=public_url,
                    hostname=hostname,
                    tunnel_name=tunnel_name,
                    tunnel_id=tunnel_id,
                    service_active=False,
                    logged_in=logged_in,
                    login_in_progress=login_in_progress,
                    tunnel_running=False,
                )
            healthy = self._health(public_url)
            if healthy is False:
                return self._payload(
                    state="error",
                    installed=True,
                    reason="The tunnel process is up but the public hostname is not responding.",
                    public_url=public_url,
                    hostname=hostname,
                    tunnel_name=tunnel_name,
                    tunnel_id=tunnel_id,
                    service_active=service_active,
                    logged_in=logged_in,
                    login_in_progress=login_in_progress,
                    tunnel_running=tunnel_running,
                )
            return self._payload(
                state="running",
                installed=True,
                public_url=public_url,
                hostname=hostname,
                tunnel_name=tunnel_name,
                tunnel_id=tunnel_id,
                service_active=service_active,
                logged_in=logged_in,
                login_in_progress=login_in_progress,
                tunnel_running=tunnel_running,
            )

        if failure and not login_in_progress:
            return self._payload(
                state="error",
                installed=True,
                reason=failure,
                hostname=hostname,
                tunnel_name=tunnel_name,
                tunnel_id=tunnel_id,
                service_active=service_active,
                logged_in=logged_in,
                login_in_progress=login_in_progress,
                tunnel_running=tunnel_running,
            )

        if service_active or logged_in:
            return self._payload(
                state="needs_hostname",
                installed=True,
                hostname=hostname,
                tunnel_name=tunnel_name,
                tunnel_id=tunnel_id,
                service_active=service_active,
                logged_in=logged_in,
                login_in_progress=login_in_progress,
                tunnel_running=tunnel_running,
            )

        return self._payload(
            state="needs_login",
            installed=True,
            hostname=hostname,
            tunnel_name=tunnel_name,
            tunnel_id=tunnel_id,
            service_active=service_active,
            logged_in=logged_in,
            login_in_progress=login_in_progress,
            tunnel_running=tunnel_running,
        )

    def login(self, config: Dict[str, Any]) -> Dict[str, Any]:
        current = self.status(config)
        if current["state"] == "not_installed" or current["logged_in"] or current["service_active"]:
            return current
        if self._login_alive():
            return current
        self._clear_error()
        with self._lock:
            self._output.clear()
            self._auth_url = None
        try:
            process = self._popen(
                [self._binary(self._settings(config)), "tunnel", "login"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=self._env(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self._set_error(f"Could not start Cloudflare login: {exc}")
            return self.status(config)
        with self._lock:
            self._login_process = process
        threading.Thread(
            target=self._read_process, args=(process,), kwargs={"login": True},
            daemon=True,
        ).start()
        try:
            process.wait(timeout=0.8)
        except subprocess.TimeoutExpired:
            pass
        return self.status(config)

    def _list_tunnels(self, settings: Dict[str, Any]) -> list[dict]:
        result = self._run(
            [self._binary(settings), "tunnel", "list", "--output", "json"], settings)
        if result.returncode != 0:
            return []
        try:
            data = json.loads(result.stdout or "[]")
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    def _ensure_tunnel(self, name: str, settings: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        for item in self._list_tunnels(settings):
            if str(item.get("name") or "") == name:
                return str(item.get("id") or "") or None, None
        result = self._run([self._binary(settings), "tunnel", "create", name], settings)
        output = f"{result.stdout}\n{result.stderr}".strip()
        if result.returncode != 0:
            return None, output or "Could not create the Cloudflare tunnel."
        match = _TUNNEL_ID.search(output)
        if not match:
            for item in self._list_tunnels(settings):
                if str(item.get("name") or "") == name:
                    return str(item.get("id") or "") or None, None
            return None, "Cloudflare created the tunnel but did not return its id."
        return match.group(0), None

    def _write_config(self, tunnel_id: str, hostname: str, tunnel_name: str,
                      settings: Dict[str, Any]) -> Optional[str]:
        root, _, config_path = self._dirs()
        root.mkdir(parents=True, exist_ok=True)
        home_credentials = Path.home() / ".cloudflared" / f"{tunnel_id}.json"
        data_credentials = root / f"{tunnel_id}.json"
        credentials = home_credentials if home_credentials.exists() else data_credentials
        if not credentials.exists():
            return f"Cloudflare credentials were not found for tunnel {tunnel_id}."
        config_path.write_text(
            f"tunnel: {tunnel_id}\n"
            f"credentials-file: {credentials}\n"
            "ingress:\n"
            f"  - hostname: {hostname}\n"
            f"    service: {settings.get('service_url') or 'http://127.0.0.1:8000'}\n"
            "  - service: http_status:404\n",
            encoding="utf-8",
        )
        return None

    def _start_tunnel(self, tunnel_id: str, settings: Dict[str, Any]) -> None:
        if self._tunnel_alive():
            return
        _, _, config_path = self._dirs()
        process = self._popen(
            [self._binary(settings), "tunnel", "--config", str(config_path), "run", tunnel_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=self._env(),
        )
        with self._lock:
            self._tunnel_process = process
        threading.Thread(
            target=self._read_process, args=(process,), kwargs={"login": False},
            daemon=True,
        ).start()

    def connect(
        self,
        config: Dict[str, Any],
        hostname: str,
        tunnel_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        hostname = (hostname or "").strip().lower().removeprefix("https://").rstrip("/")
        if not _HOSTNAME.match(hostname):
            return self._payload(
                state="error", installed=True,
                reason="Enter a public hostname such as vira.example.com.",
            )
        current = self.status(config)
        if current["state"] == "not_installed":
            return current

        if current["service_active"]:
            if not self._health(f"https://{hostname}"):
                return self._payload(
                    state="error",
                    installed=True,
                    reason=(
                        f"https://{hostname}/health is not reachable. "
                        "Check the public hostname configured for the running cloudflared tunnel."
                    ),
                    hostname=hostname,
                    service_active=True,
                    logged_in=current["logged_in"],
                )
            return self._payload(
                state="running", installed=True,
                public_url=f"https://{hostname}", hostname=hostname,
                service_active=True, logged_in=current["logged_in"],
                tunnel_running=True,
            )

        if not current["logged_in"]:
            started = self.login(config)
            started["reason"] = "Finish Cloudflare login, then create the tunnel."
            return started

        name = (tunnel_name or self._settings(config).get("tunnel_name") or "vira").strip()
        tunnel_id, error = self._ensure_tunnel(name, self._settings(config))
        if error or not tunnel_id:
            self._set_error(error or "Could not create the tunnel.")
            return self.status(config)

        route = self._run([
            self._binary(self._settings(config)),
            "tunnel", "route", "dns", tunnel_id, hostname,
        ])
        route_output = f"{route.stdout}\n{route.stderr}".lower()
        if route.returncode != 0 and "already exists" not in route_output:
            self._set_error(
                f"Could not route {hostname}: "
                f"{(route.stderr or route.stdout or '').strip()[:500]}"
            )
            return self.status(config)

        error = self._write_config(tunnel_id, hostname, name, self._settings(config))
        if error:
            self._set_error(error)
            return self.status(config)
        try:
            self._start_tunnel(tunnel_id, self._settings(config))
        except (OSError, subprocess.SubprocessError) as exc:
            self._set_error(f"Could not start the tunnel: {exc}")
            return self.status(config)

        return self._payload(
            state="running", installed=True,
            public_url=f"https://{hostname}", hostname=hostname,
            tunnel_name=name, tunnel_id=tunnel_id, logged_in=True,
            tunnel_running=self._tunnel_alive(),
        )
