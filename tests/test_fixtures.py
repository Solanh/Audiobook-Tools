from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fixtures.generator import build_fixture, load_fixture_manifest


class FixtureTests(unittest.TestCase):
    def test_manifest_contains_only_synthetic_layout_descriptions(self) -> None:
        manifest = load_fixture_manifest()
        self.assertEqual(manifest["schema_version"], 1)
        self.assertGreaterEqual(len(manifest["fixtures"]), 4)
        self.assertTrue(all("tree" in fixture for fixture in manifest["fixtures"]))

    def test_build_fixture_creates_requested_tiny_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            created = build_fixture(root, "multi-disc-tagged-book", content=b"fixture")

            self.assertEqual(len(created), 2)
            self.assertTrue(all(path.exists() for path in created))
            self.assertTrue(all(path.read_bytes() == b"fixture" for path in created))
            self.assertTrue(any("Disc 1" in path.parts for path in created))
            self.assertTrue(any("Disc 2" in path.parts for path in created))


if __name__ == "__main__":
    unittest.main()
