"""Guided Tailscale setup state tests."""
import json
import os
import subprocess
import unittest

from vira.access import TailscaleProvider
from vira.access.tailscale_setup import TailscaleController


def _completed(payload: dict, code: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        ["tailscale"], code, json.dumps(payload), stderr
    )


def _payload(state: str = "NeedsLogin", auth_url: str = "") -> dict:
    return {
        "BackendState": state,
        "AuthURL": auth_url,
        "Self": {
            "HostName": "vira-host",
            "DNSName": "vira-host.tail1234.ts.net.",
            "TailscaleIPs": ["100.101.102.103"],
        },
        "CurrentTailnet": {"Name": "example.com"},
    }


def _config(**tailscale) -> dict:
    settings = {
        "enabled": True,
        "binary": "tailscale",
        "scheme": "http",
        "port": 8000,
        "prefer_dns_name": True,
        "timeout_seconds": 2,
    }
    settings.update(tailscale)
    return {"access": {"provider": "tailscale", "tailscale": settings}}


class TailscaleControllerTests(unittest.TestCase):
    def _controller(self, payload: dict, *, which=True, runner=None):
        return TailscaleController(
            provider=TailscaleProvider(
                runner=lambda *args, **kwargs: _completed(payload),
                which=lambda binary: f"/usr/bin/{binary}" if which else None,
            ),
            which=lambda binary: f"/usr/bin/{binary}" if which else None,
            runner=runner,
        )

    def test_reports_missing_cli_with_install_command(self):
        status = self._controller(_payload(), which=False).status(_config())
        self.assertEqual(status["state"], "not_installed")
        self.assertFalse(status["installed"])
        self.assertIn("tailscale.com/install.sh", status["install_command"])
        self.assertTrue(status["next_steps"])

    def test_reports_login_url_and_qr(self):
        controller = self._controller(
            _payload(auth_url="https://login.tailscale.com/a/example"))
        status = controller.status(_config())
        self.assertEqual(status["state"], "needs_login")
        self.assertEqual(status["auth_url"], "https://login.tailscale.com/a/example")
        self.assertTrue(status["auth_qr"].startswith("data:image/svg+xml;base64,"))
        self.assertTrue(status["can_connect"])
        self.assertTrue(status["can_use_auth_key"])

    def test_reports_running_address_and_tailnet(self):
        status = self._controller(_payload("Running")).status(_config())
        self.assertEqual(status["state"], "running")
        self.assertTrue(status["connected"])
        self.assertEqual(status["address"], "http://vira-host.tail1234.ts.net:8000")
        self.assertEqual(status["hostname"], "vira-host.tail1234.ts.net")
        self.assertEqual(status["tailnet"], "example.com")
        self.assertFalse(status["can_use_auth_key"])

    def test_daemon_failure_has_actionable_state(self):
        controller = TailscaleController(
            provider=TailscaleProvider(
                runner=lambda *args, **kwargs: subprocess.CompletedProcess(
                    ["tailscale"], 1, "", "failed to connect to local tailscaled"
                ),
                which=lambda binary: "/usr/bin/tailscale",
            ),
            which=lambda binary: "/usr/bin/tailscale",
        )
        status = controller.status(_config())
        self.assertEqual(status["state"], "daemon_unavailable")
        self.assertIn("tailscaled", " ".join(status["next_steps"]))

    def test_auth_key_connect_uses_a_private_file_and_never_returns_the_key(self):
        seen = []
        contents = {}
        paths = []

        def runner(command, **kwargs):
            seen.append(command)
            flag = next(arg for arg in command if arg.startswith("--auth-key="))
            path = flag.split("file:", 1)[1]
            paths.append(path)
            with open(path, encoding="utf-8") as handle:
                contents[path] = handle.read()
            return _completed(_payload(), code=0)

        controller = self._controller(_payload(), runner=runner)
        key = "tskey-auth-example-secret"
        status = controller.connect(_config(), auth_key=key)
        self.assertTrue(seen)
        self.assertTrue(seen[0][-1].startswith("--auth-key=file:"))
        self.assertNotIn(key, " ".join(seen[0]))
        self.assertEqual(contents[paths[0]], key)
        self.assertFalse(os.path.exists(paths[0]))
        self.assertNotIn(key, json.dumps(status))

    def test_browser_connect_starts_tailscale_up_without_an_auth_key(self):
        started = []

        class FakeProcess:
            def __init__(self, command, **kwargs):
                started.append(command)
                self.stdout = iter(["To authenticate, visit: https://login.tailscale.com/a/example\n"])
                self._code = 0

            def poll(self):
                return None

            def wait(self, timeout=None):
                self._code = 0
                return 0

        controller = TailscaleController(
            provider=TailscaleProvider(
                runner=lambda *args, **kwargs: _completed(
                    _payload(auth_url="https://login.tailscale.com/a/example")
                ),
                which=lambda binary: "/usr/bin/tailscale",
            ),
            which=lambda binary: "/usr/bin/tailscale",
            popen=FakeProcess,
        )
        status = controller.connect(_config())
        self.assertEqual(status["state"], "needs_login")
        self.assertTrue(started)
        self.assertEqual(started[0][1], "up")
        self.assertFalse(any(arg.startswith("--auth-key=") for arg in started[0]))

    def test_rejects_malformed_auth_key(self):
        controller = self._controller(_payload())
        status = controller.connect(_config(), auth_key="not-a-key")
        self.assertEqual(status["state"], "error")
        self.assertIn("auth key", status["reason"].lower())

    def test_permission_failure_explains_operator_setup(self):
        def runner(command, **kwargs):
            return subprocess.CompletedProcess(
                command, 1, "", "must be root: use sudo tailscale up"
            )

        controller = self._controller(_payload(), runner=runner)
        status = controller.connect(_config(), auth_key="tskey-auth-example")
        self.assertEqual(status["state"], "error")
        self.assertIn("operator", " ".join(status["next_steps"]).lower())


if __name__ == "__main__":
    unittest.main()
