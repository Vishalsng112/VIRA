"""Guided Tailscale setup for the dashboard.

The controller only orchestrates the Tailscale CLI. It never creates or stores
Tailscale accounts, and an auth key is used in-process and then discarded.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from collections import deque
from typing import Any, Callable, Deque, Dict, Optional

from .providers import TailscaleProvider
from .qr import qr_svg_data_uri

_HOSTNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,62}$")
def _install_command() -> str:
    if sys.platform.startswith("linux"):
        return "curl -fsSL https://tailscale.com/install.sh | sh"
    if sys.platform == "darwin":
        return "brew install --cask tailscale"
    if os.name == "nt":
        return "winget install Tailscale.Tailscale"
    return "Install Tailscale from https://tailscale.com/download"


class TailscaleController:
    def __init__(
        self,
        provider: Optional[TailscaleProvider] = None,
        which: Optional[Callable[[str], Optional[str]]] = None,
        runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
        popen: Optional[Callable[..., subprocess.Popen]] = None,
    ) -> None:
        self.provider = provider or TailscaleProvider()
        self._which = which or shutil.which
        self._runner = runner or subprocess.run
        self._popen = popen or subprocess.Popen
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._output: Deque[str] = deque(maxlen=20)
        self._last_error: Optional[str] = None

    @staticmethod
    def _settings(config: Dict[str, Any]) -> Dict[str, Any]:
        access = config.get("access") or {}
        return access.get("tailscale") or {}

    def _alive(self) -> bool:
        with self._lock:
            process = self._process
            return bool(process is not None and process.poll() is None)

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message.strip()[:1200] or None

    def _clear_error(self) -> None:
        with self._lock:
            self._last_error = None

    def _read_process(self, process: subprocess.Popen, secret: Optional[str] = None) -> None:
        try:
            for line in process.stdout or []:
                text = str(line).strip()
                if not text:
                    continue
                if secret:
                    text = text.replace(secret, "[redacted]")
                with self._lock:
                    self._output.append(text)
            code = process.wait()
            if code not in (0, None):
                with self._lock:
                    tail = "\n".join(self._output) or f"tailscale up exited with {code}"
                    self._last_error = tail[-1200:]
        except Exception as exc:  # the UI must still show a useful state
            self._set_error(f"Tailscale process failed: {exc}")
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None

    def _next_steps(self, state: str, reason: str = "") -> list[str]:
        lowered = reason.lower()
        if state == "not_installed":
            return [
                "Install Tailscale on the machine that runs VIRA.",
                "If VIRA runs in Docker, run Tailscale on the host or use a sidecar container.",
                "Then click Refresh.",
            ]
        if state == "daemon_unavailable":
            return [
                "Start the Tailscale service: sudo systemctl enable --now tailscaled",
                "Then click Connect Tailscale again.",
            ]
        if "permission" in lowered or "operator" in lowered or "root" in lowered:
            return [
                "Allow the VIRA service user to manage Tailscale:",
                "sudo tailscale set --operator=<vira-user>",
                "Then click Connect Tailscale again.",
            ]
        if state == "needs_login":
            return [
                "Open the Tailscale login URL or scan the QR code.",
                "Sign in to Tailscale or create an account.",
                "VIRA detects completion automatically.",
            ]
        if state == "stopped":
            return ["Click Connect Tailscale to start the private tailnet."]
        return []

    def _payload(
        self,
        *,
        state: str,
        installed: bool,
        reason: Optional[str] = None,
        auth_url: Optional[str] = None,
        hostname: Optional[str] = None,
        tailnet: Optional[str] = None,
        address: Optional[str] = None,
        login_in_progress: bool = False,
    ) -> Dict[str, Any]:
        qr = None
        if auth_url:
            try:
                qr = qr_svg_data_uri(auth_url)
            except Exception:
                qr = None
        reason = (reason or "").strip() or None
        return {
            "state": state,
            "installed": installed,
            "connected": state == "running",
            "address": address,
            "hostname": hostname,
            "tailnet": tailnet,
            "auth_url": auth_url or None,
            "auth_qr": qr,
            "reason": reason,
            "next_steps": self._next_steps(state, reason or ""),
            "install_command": _install_command() if state == "not_installed" else None,
            "login_in_progress": login_in_progress,
            "can_connect": installed and state in ("needs_login", "stopped", "error"),
            "can_use_auth_key": installed and state != "running",
            "provider": "tailscale",
        }

    def status(self, config: Dict[str, Any]) -> Dict[str, Any]:
        settings = self._settings(config)
        binary = self.provider.binary(settings)
        if not self._which(binary):
            return self._payload(state="not_installed", installed=False)

        try:
            data = self.provider.status_json(settings)
        except RuntimeError as exc:
            reason = str(exc)
            lowered = reason.lower()
            state = "daemon_unavailable" if (
                "tailscaled" in lowered or "daemon" in lowered or "connect" in lowered
            ) else "error"
            with self._lock:
                failure = self._last_error
            return self._payload(
                state=state,
                installed=True,
                reason=failure or reason,
                login_in_progress=self._alive(),
            )

        parsed = self.provider.parse_status(data, settings)
        endpoint = parsed.get("endpoint")
        backend = str(parsed.get("backend_state") or "")
        auth_url = str(parsed.get("auth_url") or "").strip()
        running = bool(parsed.get("available"))
        alive = self._alive()
        with self._lock:
            failure = self._last_error

        if running:
            self._clear_error()
            return self._payload(
                state="running",
                installed=True,
                hostname=parsed.get("host"),
                tailnet=parsed.get("tailnet"),
                address=endpoint.url if endpoint else None,
            )

        if backend == "NeedsLogin":
            state = "needs_login"
            reason = None
        elif backend in ("Stopped", "NoState", ""):
            state = "stopped"
            reason = None
        else:
            state = "error"
            reason = str(parsed.get("reason") or "")

        if failure and not alive:
            state = "error"
            reason = failure

        return self._payload(
            state=state,
            installed=True,
            reason=reason,
            auth_url=auth_url,
            hostname=parsed.get("host"),
            tailnet=parsed.get("tailnet"),
            address=endpoint.url if endpoint else None,
            login_in_progress=alive,
        )

    def _command(self, settings: Dict[str, Any], hostname: Optional[str],
                 auth_key: Optional[str]) -> list[str]:
        command = [self.provider.binary(settings), "up"]
        chosen_host = hostname or settings.get("hostname")
        if chosen_host:
            command.append(f"--hostname={chosen_host}")
        if auth_key:
            # Tailscale accepts `file:` so the secret never appears in the
            # process list. The caller removes the file immediately after use.
            command.append(f"--auth-key={auth_key}")
        return command

    def connect(
        self,
        config: Dict[str, Any],
        auth_key: Optional[str] = None,
        hostname: Optional[str] = None,
    ) -> Dict[str, Any]:
        settings = self._settings(config)
        hostname = (hostname or "").strip() or None
        if hostname and not _HOSTNAME.match(hostname):
            return self._payload(
                state="error",
                installed=True,
                reason="Hostname must contain only letters, numbers, dots and dashes.",
            )

        current = self.status(config)
        if current["state"] == "running":
            return current
        if not current["installed"]:
            return current

        key = (auth_key or "").strip() or None
        if key and not key.startswith("tskey-"):
            return self._payload(
                state="error",
                installed=True,
                reason="That does not look like a Tailscale auth key.",
            )

        self._clear_error()
        with self._lock:
            self._output.clear()

        if key:
            fd, key_path = tempfile.mkstemp(prefix="vira-tskey-", suffix=".txt")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(key)
                command = self._command(settings, hostname, f"file:{key_path}")
                try:
                    result = self._runner(
                        command,
                        capture_output=True,
                        text=True,
                        timeout=45,
                        check=False,
                    )
                except (OSError, subprocess.SubprocessError) as exc:
                    self._set_error(f"Could not run Tailscale: {exc}")
                    return self.status(config)
                output = "\n".join(
                    part for part in ((result.stdout or ""), (result.stderr or "")) if part
                ).strip()
                output = output.replace(key, "[redacted]")
                if result.returncode != 0:
                    self._set_error(output or f"tailscale up exited with {result.returncode}")
            finally:
                try:
                    os.unlink(key_path)
                except OSError:
                    pass
            return self.status(config)

        if self._alive():
            return self.status(config)

        command = self._command(settings, hostname, None)
        try:
            process = self._popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self._set_error(f"Could not run Tailscale: {exc}")
            return self.status(config)

        with self._lock:
            self._process = process
        threading.Thread(
            target=self._read_process, args=(process,), daemon=True
        ).start()
        # `tailscale up` may keep running while the user completes login. Give
        # it a moment so the first status poll can expose the auth URL.
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass
        return self.status(config)
