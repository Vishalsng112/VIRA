"""Tests for the first-run doctor checks (no Docker, Ollama or network needed)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vira import doctor


class DoctorCheckTests(unittest.TestCase):
    def test_chatbot_states(self):
        self.assertEqual(doctor.check_chatbot({}).status, "fail")
        disabled = {"agents": [{"name": "Chatbot", "class": "ChatAgent", "enabled": False}]}
        self.assertEqual(doctor.check_chatbot(disabled).status, "fail")
        enabled = {"agents": [{"name": "Chatbot", "class": "ChatAgent", "enabled": True}]}
        self.assertEqual(doctor.check_chatbot(enabled).status, "ok")

    def test_master_key_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / "master.key"
            with mock.patch.dict(os.environ, {"VIRA_MASTER_KEY_FILE": str(key)}, clear=False):
                os.environ.pop("VIRA_MASTER_KEY", None)
                self.assertEqual(doctor.check_master_key().status, "warn")
                key.write_bytes(b"x" * 44)
                self.assertEqual(doctor.check_master_key().status, "ok")
                key.write_bytes(b"")
                self.assertEqual(doctor.check_master_key().status, "fail")

    def test_master_key_env_override(self):
        with mock.patch.dict(os.environ, {"VIRA_MASTER_KEY": "a-secret"}, clear=False):
            self.assertEqual(doctor.check_master_key().status, "ok")

    def test_database_writable(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {"auth": {"database_url": f"sqlite:///{tmp}/vira.sqlite3"}}
            check = doctor.check_database(config)
            self.assertEqual(check.status, "ok", check.detail)

    def test_config_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("llm:\n  default_model: test\n", encoding="utf-8")
            self.assertEqual(doctor.check_config(str(path)).status, "ok")
            self.assertEqual(doctor.check_config(str(Path(tmp) / "missing.yaml")).status, "fail")

    def test_model_check_reports_missing_model(self):
        config = {"llm": {"default_model": "wanted:1b",
                          "models": [{"provider": "ollama", "model": "wanted:1b"}]}}
        with mock.patch("vira.llm.catalog.list_ollama_models", return_value=[]):
            check = doctor.check_model(config, "http://ollama.test", True)
        self.assertEqual(check.status, "fail")
        self.assertIn("wanted:1b", check.summary)

    def test_model_check_reports_ready(self):
        config = {"llm": {"default_model": "ready:1b",
                          "models": [{"provider": "ollama", "model": "ready:1b", "num_ctx": 8192}]}}
        with mock.patch(
            "vira.llm.catalog.list_ollama_models",
            return_value=[{"name": "ready:1b"}],
        ), mock.patch(
            "vira.llm.catalog.show_ollama_model",
            return_value={"model_info": {"general.context_length": 8192}},
        ):
            check = doctor.check_model(config, "http://ollama.test", True)
        self.assertEqual(check.status, "ok", check.detail)
        self.assertIn("8,192", check.detail)

    def test_small_model_warns_about_tool_use(self):
        config = {"llm": {"default_model": "tiny:3b",
                          "models": [{"provider": "ollama", "model": "tiny:3b"}]}}
        with mock.patch(
            "vira.llm.catalog.list_ollama_models", return_value=[{"name": "tiny:3b"}],
        ), mock.patch(
            "vira.llm.catalog.show_ollama_model",
            return_value={"details": {"parameter_size": "3.2B"},
                          "model_info": {"llama.context_length": 8192}},
        ):
            check = doctor.check_model(config, "http://ollama.test", True)
        self.assertEqual(check.status, "warn")
        self.assertIn("7B", check.detail)

    def test_doctor_report_shape_without_external_services(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.yaml"
            config.write_text(
                "llm:\n  default_model: test:1b\n"
                "  models:\n    - provider: ollama\n      model: test:1b\n"
                "agents:\n  - name: Chatbot\n    class: ChatAgent\n    enabled: true\n"
                f"auth:\n  database_url: sqlite:///{tmp}/vira.sqlite3\n",
                encoding="utf-8",
            )
            with mock.patch("vira.llm.catalog.list_ollama_models", side_effect=OSError("offline")):
                report = doctor.run_doctor(str(config), "http://127.0.0.1:9", include_docker=False)
        payload = report.as_dict()
        names = {check["name"] for check in payload["checks"]}
        self.assertTrue({"configuration", "ollama", "model", "port", "chatbot",
                         "database", "master_key"} <= names)
        self.assertTrue(report.failed)  # Ollama is unreachable in this test


if __name__ == "__main__":
    unittest.main()
