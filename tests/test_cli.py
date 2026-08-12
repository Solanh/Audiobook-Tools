from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from media_janitor.audiobookshelf import AudiobookshelfItem, AudiobookshelfLibrary
from media_janitor.cli import main


class FakeAudiobookshelfClient:
    base_url = "https://abs.example.test"

    def libraries(self):
        return (AudiobookshelfLibrary(id="lib_1", name="Books", media_type="book"),)

    def library_items(self, library_id: str):
        self.requested_library_id = library_id
        return (
            AudiobookshelfItem(
                id="li_1",
                library_id="lib_1",
                path="/audiobooks/Warbreaker",
                title="Warbreaker",
                authors=(),
                narrators=(),
                series=(),
                duration_seconds=None,
                asin=None,
                isbn=None,
            ),
        )


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

    def test_inspect_audiobooks_handles_tagless_audio_and_stays_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Warbreaker"
            book.mkdir()
            source = book / "Chapter One.mp3"
            source.write_bytes(b"not-real-audio")
            output = root / "items.json"

            stdout = StringIO()
            with redirect_stdout(stdout):
                result = main(["inspect-audiobooks", str(root), "--json", str(output), "--pretty"])

            self.assertEqual(result, 0)
            self.assertTrue(source.exists())
            self.assertEqual(source.read_bytes(), b"not-real-audio")
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["items"]), 1)
            self.assertEqual(payload["items"][0]["item_path"], "Warbreaker")
            self.assertEqual(payload["items"][0]["title_hint"], "Warbreaker")
            file_record = payload["items"][0]["files"][0]
            self.assertTrue(file_record["embedded"] is not None or file_record["metadata_error"] is not None)

    def test_match_audiobookshelf_writes_report_without_touching_media(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Warbreaker"
            book.mkdir()
            source = book / "Chapter One.mp3"
            source.write_bytes(b"tagless-audio")
            output = root / "matches.json"

            stdout = StringIO()
            with patch("media_janitor.cli.client_from_environment", return_value=FakeAudiobookshelfClient()):
                with redirect_stdout(stdout):
                    result = main(
                        [
                            "match-audiobookshelf",
                            str(root),
                            "--json",
                            str(output),
                            "--pretty",
                            "--candidate-limit",
                            "1",
                        ]
                    )

            self.assertEqual(result, 0)
            self.assertEqual(source.read_bytes(), b"tagless-audio")
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["local_items"], 1)
            self.assertEqual(payload["audiobookshelf_items"], 1)
            self.assertEqual(payload["matches"][0]["candidates"][0]["audiobookshelf_item"]["id"], "li_1")


if __name__ == "__main__":
    unittest.main()
