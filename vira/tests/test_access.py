"""Access-provider resolution tests, including Tailscale discovery."""
import json
import subprocess
import unittest

from starlette.requests import Request

from vira.access import (
    AccessResolver,
    CustomProvider,
    RequestProvider,
    TailscaleProvider,
)


def _request(url: str = "http://192.168.1.10:8000") -> Request:
    scheme, rest = url.split("://", 1)
    host, _, port = rest.partition(":")
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": scheme,
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("192.168.1.50", 50000),
        "server": (host, int(port or 80)),
    })


def _completed(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        ["tailscale", "status", "--json"], 0, json.dumps(payload), ""
    )


def _tailscale_payload(state: str = "Running") -> dict:
    return {
        "BackendState": state,
        "Self": {
            "HostName": "vira-host",
            "DNSName": "vira-host.tail1234.ts.net.",
            "TailscaleIPs": ["100.101.102.103", "fd7a:115c:a1e0::1"],
        },
        "CurrentTailnet": {
            "Name": "example.com",
            "MagicDNSSuffix": "tail1234.ts.net",
        },
    }


def _resolver(runner, which=lambda binary: f"/usr/bin/{binary}") -> AccessResolver:
    return AccessResolver([
        RequestProvider(),
        CustomProvider(),
        TailscaleProvider(runner=runner, which=which),
    ])


def _config(**access) -> dict:
    tailscale = {
        "enabled": True,
        "binary": "tailscale",
        "scheme": "http",
        "port": 8000,
        "prefer_dns_name": True,
        "timeout_seconds": 2,
    }
    tailscale.update(access.pop("tailscale", {}))
    return {"access": {"provider": "auto", "tailscale": tailscale, **access}}


class AccessResolverTests(unittest.TestCase):
    def test_auto_prefers_tailscale_private_address(self):
        resolver = _resolver(lambda *args, **kwargs: _completed(_tailscale_payload()))
        resolution = resolver.resolve(_request(), _config())
        self.assertEqual(resolution.endpoint.kind, "tailscale")
        self.assertEqual(
            resolution.endpoint.url, "http://vira-host.tail1234.ts.net:8000")
        self.assertEqual(resolution.warnings, [])
        self.assertEqual(
            [item.kind for item in resolution.candidates],
            ["tailscale", "request"],
        )

    def test_auto_falls_back_with_a_warning_when_tailscale_is_missing(self):
        resolver = _resolver(
            lambda *args, **kwargs: _completed({}), which=lambda binary: None)
        resolution = resolver.resolve(_request(), _config())
        self.assertEqual(resolution.endpoint.kind, "request")
        self.assertEqual(
            resolution.endpoint.url, "http://192.168.1.10:8000")
        self.assertIn("Tailscale CLI not found", resolution.warnings[0])

    def test_tailscale_https_on_443_omits_the_explicit_port(self):
        resolver = _resolver(lambda *args, **kwargs: _completed(_tailscale_payload()))
        config = _config(tailscale={"scheme": "https", "port": 443})
        resolution = resolver.resolve(_request(), config)
        self.assertEqual(
            resolution.endpoint.url, "https://vira-host.tail1234.ts.net")

    def test_tailscale_uses_ipv4_when_dns_is_disabled(self):
        resolver = _resolver(lambda *args, **kwargs: _completed(_tailscale_payload()))
        config = _config(tailscale={"prefer_dns_name": False})
        resolution = resolver.resolve(_request(), config)
        self.assertEqual(
            resolution.endpoint.url, "http://100.101.102.103:8000")

    def test_tailscale_not_connected_falls_back(self):
        resolver = _resolver(
            lambda *args, **kwargs: _completed(_tailscale_payload("Stopped")))
        resolution = resolver.resolve(_request(), _config())
        self.assertEqual(resolution.endpoint.kind, "request")
        self.assertIn("Tailscale is stopped", resolution.warnings[0])

    def test_explicit_custom_url_wins_in_auto_mode(self):
        resolver = _resolver(lambda *args, **kwargs: _completed(_tailscale_payload()))
        config = _config(public_url="https://vira.example.com/")
        resolution = resolver.resolve(_request(), config)
        self.assertEqual(resolution.endpoint.kind, "custom")
        self.assertEqual(resolution.endpoint.url, "https://vira.example.com")

    def test_request_mode_ignores_tailscale(self):
        resolver = _resolver(lambda *args, **kwargs: _completed(_tailscale_payload()))
        config = _config(provider="request")
        resolution = resolver.resolve(_request(), config)
        self.assertEqual(resolution.endpoint.kind, "request")
        self.assertEqual(resolution.warnings, [])

    def test_tailscale_mode_reports_a_warning_when_disabled(self):
        resolver = _resolver(lambda *args, **kwargs: _completed(_tailscale_payload()))
        config = _config(tailscale={"enabled": False})
        config["access"]["provider"] = "tailscale"
        resolution = resolver.resolve(_request(), config)
        self.assertEqual(resolution.endpoint.kind, "request")
        self.assertIn("disabled", resolution.warnings[0])

    def test_status_lists_every_provider(self):
        resolver = _resolver(lambda *args, **kwargs: _completed(_tailscale_payload()))
        status = resolver.status(_request(), _config())
        self.assertEqual(status["mode"], "auto")
        self.assertEqual(status["resolved"]["kind"], "tailscale")
        kinds = {provider["kind"] for provider in status["providers"]}
        self.assertEqual(kinds, {"request", "custom", "tailscale"})
        self.assertTrue(
            next(item for item in status["providers"]
                 if item["kind"] == "tailscale")["available"])


if __name__ == "__main__":
    unittest.main()
