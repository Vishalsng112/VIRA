"""The deterministic tool-use benchmark must stay green across releases."""
import unittest

from vira.agent.benchmark import (
    run_offline,
    scenario_database_question,
    scenario_device_question,
    scenario_malformed_json,
    scenario_rag_question,
    scenario_repeated_call,
    scenario_unknown_tool,
    scenario_web_failure_recovery,
)


class BenchmarkTests(unittest.TestCase):
    def test_every_reserved_category_has_a_scenario(self):
        results = run_offline()
        categories = {item.category for item in results}
        self.assertTrue({"device", "database", "rag", "web", "robustness"} <= categories)

    def test_all_scenarios_pass(self):
        for item in run_offline():
            self.assertTrue(item.passed, f"{item.name}: {item.detail}")

    def test_individual_contracts(self):
        self.assertTrue(scenario_device_question().passed)
        self.assertTrue(scenario_database_question().passed)
        self.assertTrue(scenario_rag_question().passed)
        self.assertTrue(scenario_web_failure_recovery().passed)
        self.assertTrue(scenario_repeated_call().passed)
        self.assertTrue(scenario_malformed_json().passed)
        self.assertTrue(scenario_unknown_tool().passed)


if __name__ == "__main__":
    unittest.main()
