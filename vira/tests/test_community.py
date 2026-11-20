"""Phase 6 community assets: examples, backlog, changelog, templates and docs."""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class CommunityAssetTests(unittest.TestCase):
    def test_good_first_issue_backlog_is_curated(self):
        entries = json.loads((ROOT / ".github/good-first-issues.json").read_text())
        self.assertGreaterEqual(len(entries), 8)
        ids = [item["id"] for item in entries]
        self.assertEqual(len(ids), len(set(ids)))
        for item in entries:
            self.assertTrue(item["title"])
            self.assertTrue(item["acceptance"])
            self.assertIn("good first issue", item["labels"])
            for path in item["files"]:
                if path.endswith("/"):
                    self.assertTrue((ROOT / path).exists(), path)
                else:
                    self.assertTrue((ROOT / path).exists(), path)

    def test_examples_are_documented_and_tested(self):
        plugin_manifests = list((ROOT / "examples/plugins").glob("*/vira-plugin.json"))
        self.assertGreaterEqual(len(plugin_manifests), 3)
        for manifest_path in plugin_manifests:
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(manifest["api_version"], "1")
            self.assertTrue(manifest["entrypoint"])
            self.assertTrue((manifest_path.parent / "README.md").exists())
        self.assertTrue((ROOT / "examples/mcp/notes_server.py").exists())
        self.assertTrue((ROOT / "examples/mcp/README.md").exists())
        self.assertTrue((ROOT / "vira/tests/test_examples.py").exists())

    def test_changelog_and_release_check(self):
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [Unreleased]", changelog)
        sys.path.insert(0, str(ROOT))
        from vira import __version__

        self.assertIn(f"## [{__version__}]", changelog)
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/release_tools.py"), "check",
             f"v{__version__}"],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_issue_templates_are_valid_yaml(self):
        templates = ROOT / ".github" / "ISSUE_TEMPLATE"
        names = {
            "bug_report.yml", "feature_request.yml", "good_first_issue.yml",
            "decision_proposal.yml", "showcase_submission.yml",
            "release_checklist.yml",
        }
        for name in names:
            payload = yaml.safe_load((templates / name).read_text(encoding="utf-8"))
            self.assertIn("name", payload, name)
            self.assertIn("body", payload, name)
        config = yaml.safe_load((templates / "config.yml").read_text(encoding="utf-8"))
        self.assertFalse(config["blank_issues_enabled"])

    def test_release_and_security_workflows_are_valid_yaml(self):
        for name in ("release.yml", "security.yml", "build-client.yml"):
            payload = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
            self.assertIn("jobs", payload, name)

    def test_docs_are_linked(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for target in (
            "CHANGELOG.md",
            "docs/user/showcase.md",
            "docs/dev/releases.md",
            "docs/dev/decision-log.md",
            "docs/dev/good-first-issues.md",
            "CONTRIBUTING.md",
            "CODE_OF_CONDUCT.md",
        ):
            self.assertIn(target, readme, target)
        for path in (
            "docs/dev/releases.md",
            "docs/dev/decision-log.md",
            "docs/dev/good-first-issues.md",
            "docs/user/showcase.md",
        ):
            self.assertTrue((ROOT / path).exists(), path)

    def test_contributor_guide_contains_plain_language_map(self):
        guide = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        for phrase in ("VIRA in plain language", "Repository map",
                       "Your first change", "response within"):
            self.assertIn(phrase, guide)
        self.assertIn("examples/plugins/reading_list", guide)
        self.assertIn("examples/mcp/notes_server.py", guide)


if __name__ == "__main__":
    unittest.main()
