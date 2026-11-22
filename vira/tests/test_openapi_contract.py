"""OpenAPI compatibility test for the public /api/v1 surface."""
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from vira.api.app import create_app
from vira.auth import database


class _Config:
    def get(self, key, default=None):
        return default

    def get_all(self):
        return {}

    def set(self, key, value):
        pass

    def save(self, value):
        pass


class _Bus:
    def subscribe_all(self, callback):
        return "sub"

    def unsubscribe_all(self, callback):
        return True


class _Metrics:
    def record_error(self, *args, **kwargs):
        pass

    def increment_counter(self, *args, **kwargs):
        pass

    def observe_histogram(self, *args, **kwargs):
        pass


class _Kernel:
    config_manager = _Config()
    event_bus = _Bus()
    metrics_manager = _Metrics()
    local_device = None
    device_service = None
    ingestion_service = None

    def is_running(self):
        return True


class RedactedConfigTests(unittest.TestCase):
    def test_redacted_values_inside_lists_are_preserved(self):
        from vira.api.app import _preserve_redacted_values

        existing = {"agents": [{"config": {"max_tokens": 65536, "temperature": 0.1}}]}
        incoming = {"agents": [{"config": {"max_tokens": "***", "temperature": 0.2}}]}
        merged = _preserve_redacted_values(incoming, existing)
        self.assertEqual(merged["agents"][0]["config"]["max_tokens"], 65536)
        self.assertEqual(merged["agents"][0]["config"]["temperature"], 0.2)


class OpenApiContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "openapi.sqlite3"
        self.app = create_app(_Kernel())
        self.client = TestClient(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_health_is_public_summary_without_session(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")
        self.assertEqual(response.json()["service"], "vira-server")

    def test_required_paths_are_published(self):
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        schema = response.json()
        self.assertIn("info", schema)
        paths = set(schema["paths"])
        required = {
            "/api/v1/auth/login",
            "/api/v1/devices",
            "/api/v1/devices/{device_id}/events:batch",
            "/api/v1/insights/summary",
            "/api/v1/insights/context",
            "/api/v1/admin/users",
            "/api/v1/admin/jobs",
            "/api/v1/admin/audit/export",
            "/api/v1/admin/diagnostics",
            "/api/v1/diagnostics",
            "/api/v1/admin/approvals",
            "/api/v1/approvals",
            "/api/v1/approvals/{approval_id}",
            "/api/v1/generated",
            "/api/v1/generated/{artifact_id}",
            "/api/v1/generated/{artifact_id}/approve",
            "/api/v1/generated/{artifact_id}/enable",
            "/api/v1/generated/{artifact_id}/run",
            "/api/v1/admin/devices",
            "/api/v1/admin/fleet/ops",
            "/api/v1/devices/{device_id}/consent",
            "/api/v1/devices/{device_id}/commands",
            "/api/v1/access",
            "/api/v1/access/tailscale",
            "/api/v1/access/tailscale/connect",
            "/api/v1/access/cloudflare",
            "/api/v1/access/cloudflare/login",
            "/api/v1/access/cloudflare/connect",
            "/api/v1/devices/pairing-code",
            "/api/v1/devices/pair",
            "/api/v1/account/export",
            "/api/v1/notifications",
            "/api/v1/event-schemas",
            "/api/v1/agent-definitions",
            "/api/v1/workflows",
            "/api/v1/workflows/{workflow_id}/replay",
            "/api/v1/rag/documents",
            "/api/v1/rag/search",
            "/api/v1/runs",
            "/api/v1/runs/{run_id}/events",
            "/api/v1/runs/{run_id}/timeline",
            "/api/v1/runs/{run_id}/resume",
            "/api/v1/models",
            "/api/v1/models/select",
            "/v1/models",
            "/api/v1/memories/{memory_id}/feedback",
            "/api/v1/plugins",
            "/api/v1/plugins/sdk",
            "/api/v1/plugins/ui",
            "/api/v1/plugins/{plugin_id}/enable",
            "/api/v1/mcp/marketplace",
            "/api/v1/mcp/servers",
            "/api/v1/mcp/servers/{server_id}/policies",
            "/api/v1/organizations",
            "/api/v1/organizations/{org_id}/members",
            "/api/v1/objects",
            "/api/v1/objects/{object_id}",
            "/api/v1/usage/summary",
            "/api/v1/admin/usage",
            "/api/v1/admin/quotas",
            "/api/v1/updates/check",
            "/api/v1/updates/releases",
            "/health",
            "/agents",
            "/chat",
        }
        missing = required - paths
        self.assertFalse(missing, f"missing OpenAPI paths: {sorted(missing)}")


if __name__ == "__main__":
    unittest.main()
