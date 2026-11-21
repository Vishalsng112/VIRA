"""Structured-output parsing shared by the LLM providers."""
import unittest

from vira.llm.base import parse_json_object


class ParseJsonObjectTests(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(parse_json_object('{"a": 1}'), {"a": 1})

    def test_fenced_object(self):
        self.assertEqual(
            parse_json_object('```json\n{"a": 1}\n```'),
            {"a": 1},
        )

    def test_object_inside_prose(self):
        self.assertEqual(
            parse_json_object('Here you go: {"a": {"b": 2}} thanks'),
            {"a": {"b": 2}},
        )

    def test_dict_passthrough(self):
        value = {"a": 1}
        self.assertIs(parse_json_object(value), value)

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            parse_json_object("not json")
        with self.assertRaises(ValueError):
            parse_json_object(None)

    def test_array_is_not_an_object(self):
        with self.assertRaises(ValueError):
            parse_json_object("[1, 2, 3]")


if __name__ == "__main__":
    unittest.main()
