"""Security hardening tests: secrets, headers, CSRF origin and client IP."""
import os
import stat
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from vira.ratelimit import client_ip
from vira.security.auth_secret import resolve_auth_secret
from vira.security.http import OriginProtectionMiddleware, SecurityHeadersMiddleware


class _Config:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


class AuthSecretTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_generates_and_reuses_a_private_secret_file(self):
        config = _Config({"auth.secret_key": ""})
        first, source = resolve_auth_secret(config, self.path)
        self.assertEqual(source, "generated")
        self.assertGreaterEqual(len(first), 32)
        secret_file = self.path / "auth_secret"
        self.assertTrue(secret_file.exists())
        self.assertEqual(stat.S_IMODE(secret_file.stat().st_mode), 0o600)

        second, source = resolve_auth_secret(_Config({"auth.secret_key": ""}), self.path)
        self.assertEqual(source, "file")
        self.assertEqual(first, second)

    def test_strong_config_secret_is_preserved(self):
        config = _Config({"auth.secret_key": "x" * 64})
        secret, source = resolve_auth_secret(config, self.path)
        self.assertEqual(source, "config")
        self.assertEqual(secret, "x" * 64)
        self.assertFalse((self.path / "auth_secret").exists())

    def test_environment_secret_wins(self):
        os.environ["VIRA_AUTH_SECRET"] = "e" * 64
        try:
            secret, source = resolve_auth_secret(_Config(), self.path)
        finally:
            os.environ.pop("VIRA_AUTH_SECRET", None)
        self.assertEqual(source, "environment:VIRA_AUTH_SECRET")
        self.assertEqual(secret, "e" * 64)


class HttpSecurityTests(unittest.TestCase):
    def _app(self, allowed=()):
        app = FastAPI()

        @app.post("/write")
        async def write():
            return {"ok": True}

        @app.get("/read")
        async def read():
            return {"ok": True}

        app.add_middleware(
            OriginProtectionMiddleware,
            session_cookie="vira_session",
            allowed_origins=allowed,
        )
        app.add_middleware(SecurityHeadersMiddleware)
        return TestClient(app)

    def test_cross_site_cookie_write_is_rejected(self):
        client = self._app()
        client.cookies.set("vira_session", "session")
        response = client.post("/write", headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "csrf_blocked")

    def test_same_origin_and_configured_origin_are_allowed(self):
        client = self._app(allowed=("https://vira.example.com",))
        client.cookies.set("vira_session", "session")
        self.assertEqual(
            client.post("/write", headers={"Origin": "http://testserver"}).status_code,
            200,
        )
        self.assertEqual(
            client.post("/write", headers={"Origin": "https://vira.example.com"}).status_code,
            200,
        )

    def test_bearer_clients_and_reads_are_unaffected(self):
        client = self._app()
        client.cookies.set("vira_session", "session")
        self.assertEqual(
            client.get("/read", headers={"Origin": "https://evil.example"}).status_code,
            200,
        )
        client.cookies.clear()
        self.assertEqual(
            client.post(
                "/write",
                headers={"Origin": "https://evil.example", "Authorization": "Bearer x"},
            ).status_code,
            200,
        )

    def test_security_headers_and_hsts(self):
        client = self._app()
        response = client.get("/read", headers={"X-Forwarded-Proto": "https"})
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        self.assertIn("max-age=31536000", response.headers["strict-transport-security"])


class ClientIpTests(unittest.TestCase):
    @staticmethod
    def _request(peer, headers=None):
        return Request({
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "root_path": "",
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
            "client": (peer, 1234),
            "server": ("testserver", 443),
        })

    def test_cloudflare_ip_is_trusted_only_from_loopback(self):
        request = self._request("127.0.0.1", {"CF-Connecting-IP": "203.0.113.5"})
        self.assertEqual(client_ip(request), "203.0.113.5")

    def test_direct_client_cannot_spoof_cloudflare_header(self):
        request = self._request("198.51.100.7", {"CF-Connecting-IP": "203.0.113.5"})
        self.assertEqual(client_ip(request), "198.51.100.7")

    def test_forwarded_ip_is_used_from_loopback(self):
        request = self._request("::1", {"X-Forwarded-For": "203.0.113.9, 127.0.0.1"})
        self.assertEqual(client_ip(request), "203.0.113.9")


if __name__ == "__main__":
    unittest.main()
