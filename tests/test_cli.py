from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from media_janitor.cli import main


class CliTests(unittest.TestCase):
    def test_analyze_audiobooks_writes_read_only_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Warbreaker"
            book.mkdir()
            source = book / "Chapter Thirty-One - Warbreaker [Unabridged] 64kbps.mp3"
            source.write_bytes(b"audio")
            output = root / "analysis.json"

            stdout = StringIO()
            with redirect_stdout(stdout):
                result = main(["analyze-audiobooks", str(root), "--json", str(output), "--pretty"])

            self.assertEqual(result, 0)
            self.assertTrue(source.exists())
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["records"][0]["chapter_hint"]["number"], 31)
            self.assertIn("Warbreaker", payload["records"][0]["normalized_name"])


if __name__ == "__main__":
    unittest.main()
