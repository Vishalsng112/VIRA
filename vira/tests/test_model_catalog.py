"""Model discovery and first-run guidance helpers."""
import os
import unittest
from unittest import mock

from vira.llm import catalog, guidance


CONFIG = {
    "llm": {
        "default_model": "ornith-1.5:9b",
        "models": [{
            "name": "local-llama",
            "provider": "ollama",
            "model": "ornith-1.5:9b",
            "base_url": "http://ollama:11434",
            "num_ctx": 8192,
        }],
    }
}


class CatalogTests(unittest.TestCase):
    def test_configured_values(self):
        self.assertEqual(catalog.configured_ollama_url(CONFIG), "http://ollama:11434")
        self.assertEqual(catalog.configured_model(CONFIG), "ornith-1.5:9b")
        self.assertEqual(catalog.configured_context(CONFIG), 8192)

    def test_env_overrides(self):
        with mock.patch.dict(os.environ, {"VIRA_OLLAMA_URL": "http://remote:11434",
                                          "VIRA_OLLAMA_MODEL": "custom:1b"}):
            self.assertEqual(catalog.configured_ollama_url(CONFIG), "http://remote:11434")
            self.assertEqual(catalog.configured_model(CONFIG), "custom:1b")

    def test_context_length_extraction(self):
        self.assertEqual(
            catalog.model_context_length({"model_info": {"llama.context_length": 65536}}),
            65536,
        )
        self.assertEqual(
            catalog.model_context_length({"parameters": "temperature 0.1\nnum_ctx 4096"}),
            4096,
        )
        self.assertIsNone(catalog.model_context_length({}))


class GuidanceTests(unittest.TestCase):
    def test_tiers_follow_memory(self):
        self.assertEqual(guidance.recommend(6)["id"], "minimal")
        self.assertEqual(guidance.recommend(12)["id"], "recommended")
        self.assertEqual(guidance.recommend(24)["id"], "comfortable")
        self.assertEqual(guidance.recommend(64)["id"], "large")

    def test_warning_is_explicit_for_small_machines(self):
        self.assertTrue(guidance.recommend(4)["warning"])
        self.assertIsNone(guidance.recommend(12)["warning"])


if __name__ == "__main__":
    unittest.main()
