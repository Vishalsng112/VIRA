"""Guided Cloudflare setup tests."""
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from vira.access.cloudflare_setup import CloudflareController


def _completed(args, code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args, code, stdout, stderr)


def _config(cloudflare=None) -> dict:
    settings = {
        "enabled": True,
        "binary": "cloudflared",
        "tunnel_name": "vira",
        "service_url": "http://127.0.0.1:8000",
    }
    settings.update(cloudflare or {})
    return {"access": {"provider": "cloudflare", "cloudflare": settings}}


class CloudflareControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _controller(self, *, service=False, health=True, runner=None, popen=None):
        return CloudflareController(
            which=lambda binary: "/usr/bin/cloudflared",
            runner=runner or (lambda *a, **k: _completed(a, 0, "", "")),
            popen=popen,
            health_check=lambda url: health,
            systemctl=lambda action: service if action == "is-active" else False,
            data_dir=self.dir,
        )

    def test_missing_binary_is_reported(self):
        controller = CloudflareController(which=lambda binary: None, data_dir=self.dir)
        status = controller.status(_config())
        self.assertEqual(status["state"], "not_installed")
        self.assertIn("cloudflared", status["install_command"])

    def test_running_service_needs_a_hostname(self):
        status = self._controller(service=True).status(_config())
        self.assertEqual(status["state"], "needs_hostname")
        self.assertTrue(status["service_active"])
        self.assertFalse(status["can_login"])

    def test_existing_service_hostname_is_verified_and_used(self):
        status = self._controller(service=True).connect(_config(), "vira.example.com")
        self.assertEqual(status["state"], "running")
        self.assertEqual(status["public_url"], "https://vira.example.com")
        self.assertTrue(status["service_active"])

    def test_existing_service_rejects_an_unreachable_hostname(self):
        status = self._controller(service=True, health=False).connect(
            _config(), "vira.example.com")
        self.assertEqual(status["state"], "error")
        self.assertIn("not reachable", status["reason"])

    def test_login_flow_exposes_the_cloudflare_url(self):
        started = []

        class FakeProcess:
            def __init__(self, command, **kwargs):
                started.append(command)
                self.stdout = iter([
                    "Please open https://dash.cloudflare.com/argotunnel?callback=example\n",
                ])
                self._done = False

            def poll(self):
                return 0 if self._done else None

            def wait(self, timeout=None):
                time.sleep(0.02)
                self._done = True
                return 0

        controller = self._controller(popen=FakeProcess)
        status = controller.login(_config())
        self.assertEqual(status["state"], "needs_login")
        self.assertTrue(started)
        self.assertEqual(started[0][1:], ["tunnel", "login"])
        self.assertIn("dash.cloudflare.com/argotunnel", status["auth_url"])
        self.assertTrue(status["auth_qr"].startswith("data:image/svg+xml;base64,"))

    def test_configured_url_without_a_running_tunnel_is_stopped(self):
        status = self._controller(service=False).status(
            _config({"public_url": "https://vira.example.com"}))
        self.assertEqual(status["state"], "stopped")
        self.assertEqual(status["public_url"], "https://vira.example.com")

    def test_rejects_an_invalid_hostname(self):
        status = self._controller(service=True).connect(_config(), "not a hostname")
        self.assertEqual(status["state"], "error")
        self.assertIn("hostname", status["reason"].lower())

    def test_logged_in_mode_creates_routes_and_starts_the_tunnel(self):
        (self.dir / "cert.pem").write_text("cert")
        tunnel_id = "12345678-1234-1234-1234-123456789abc"
        (self.dir / f"{tunnel_id}.json").write_text("{}")
        commands = []

        def runner(args, **kwargs):
            commands.append(args)
            joined = " ".join(args)
            if "list" in args:
                return _completed(args, 0, json.dumps([]), "")
            if "create" in args:
                return _completed(
                    args, 0,
                    f"Created tunnel vira with id {tunnel_id}", "")
            return _completed(args, 0, "", "")

        class FakeProcess:
            def __init__(self, *args, **kwargs):
                self.stdout = iter([])

            def poll(self):
                return None

            def wait(self, timeout=None):
                return 0

        controller = self._controller(runner=runner, popen=FakeProcess)
        status = controller.connect(_config(), "vira.example.com")
        self.assertEqual(status["state"], "running")
        self.assertEqual(status["tunnel_id"], tunnel_id)
        self.assertTrue(any("route" in command and "dns" in command for command in commands))
        self.assertTrue(any("create" in command for command in commands))
        config = (self.dir / "config.yml").read_text()
        self.assertIn("hostname: vira.example.com", config)
        self.assertIn("service: http://127.0.0.1:8000", config)


if __name__ == "__main__":
    unittest.main()
