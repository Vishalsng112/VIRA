"""Release tag parsing, notes and asset naming."""
import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "release_tools", ROOT / "scripts" / "release_tools.py")
release_tools = importlib.util.module_from_spec(SPEC)
sys.modules["release_tools"] = release_tools
SPEC.loader.exec_module(release_tools)


class ReleaseTagTests(unittest.TestCase):
    def test_server_tag(self):
        release = release_tools.parse_tag("v0.4.0")
        self.assertEqual(release.product, "server")
        self.assertEqual(release.version, "0.4.0")
        self.assertFalse(release.prerelease)
        self.assertEqual(release.title, "VIRA Server 0.4.0")

    def test_server_prerelease(self):
        release = release_tools.parse_tag("v0.5.0-rc.1")
        self.assertTrue(release.prerelease)

    def test_client_tag(self):
        release = release_tools.parse_tag("vira-link-v1.0.0")
        self.assertEqual(release.product, "client")
        self.assertEqual(release.title, "VIRA Link 1.0.0")
        self.assertEqual(release.asset_prefix, "vira-link-1.0.0")

    def test_rejects_build_number_tags(self):
        with self.assertRaises(ValueError):
            release_tools.parse_tag("v0.4.0-build6")
        with self.assertRaises(ValueError):
            release_tools.parse_tag("vira-link-1.0.0-build5")

    def test_product_filter(self):
        with self.assertRaises(ValueError):
            release_tools.parse_tag("v0.4.0", product="client")


class ReleaseNotesTests(unittest.TestCase):
    def _notes(self, tag, product="auto", dist=None):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            release_tools.notes(tag, product, dist)
        return output.getvalue()

    def test_server_notes_have_standard_sections(self):
        text = self._notes("v0.4.0")
        self.assertTrue(text.startswith("## VIRA Server 0.4.0"))
        for heading in ("### Highlights", "### Upgrade", "### Downloads",
                        "### Verify", "### Changelog"):
            self.assertIn(heading, text)
        self.assertIn("sha256sum -c vira-0.4.0-checksums.txt", text)
        self.assertNotIn("\\n", text)
        self.assertNotIn("\n\n\n", text)

    def test_client_notes_hide_build_numbers(self):
        text = self._notes("vira-link-v1.0.0", "client")
        self.assertTrue(text.startswith("## VIRA Link 1.0.0"))
        self.assertNotIn("(build", text.lower())
        self.assertNotIn("-build", text.lower())
        self.assertIn("vira-link-1.0.0-android.apk", text)

    def test_notes_use_actual_asset_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "vira-0.4.0-source.tar.gz").write_bytes(b"x")
            (root / "vira-0.4.0-checksums.txt").write_text("")
            text = self._notes("v0.4.0", dist=tmp)
        self.assertIn("`vira-0.4.0-source.tar.gz`", text)
        self.assertIn("`vira-0.4.0-checksums.txt`", text)


class ReleaseAssetTests(unittest.TestCase):
    def test_writes_checksums_and_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "vira-0.4.0-source.tar.gz").write_bytes(b"content")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = release_tools.assets(
                    "v0.4.0", dist=tmp, write_checksums=True)
            self.assertEqual(code, 0)
            checksums = (root / "vira-0.4.0-checksums.txt").read_text()
        self.assertIn("vira-0.4.0-source.tar.gz", checksums)

    def test_missing_asset_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stderr(io.StringIO()):
                code = release_tools.assets("v0.4.0", dist=tmp)
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
