import unittest

from vira.llm.ollama import DEFAULT_NUM_CTX, OllamaProvider


class OllamaPayloadTests(unittest.TestCase):
    def test_sampling_settings_go_under_options(self):
        p = OllamaProvider("m", name="local", provider_extra=1, temperature=0.8, num_ctx=4096)
        payload = p._payload("hi", False, {"temperature": 0.2, "max_tokens": 300})
        self.assertEqual(payload["options"], {"temperature": 0.2, "num_predict": 300, "num_ctx": 4096})
        self.assertNotIn("temperature", payload)
        self.assertNotIn("name", payload)  # config noise is no longer sent to Ollama
        self.assertEqual((payload["model"], payload["stream"]), ("m", False))

    def test_default_context_is_raised(self):
        self.assertEqual(OllamaProvider("m")._payload("x", True, {})["options"]["num_ctx"], DEFAULT_NUM_CTX)

    def test_error_response_is_explained(self):
        with self.assertRaises(RuntimeError):
            OllamaProvider._check({"error": "model not found"})


if __name__ == "__main__":
    unittest.main()
