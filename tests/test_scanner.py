from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from media_janitor.models import FileOperation, MediaKind, OperationKind, Plan
from media_janitor.scanner import classify_extension, scan_library


class ScannerTests(unittest.TestCase):
    def test_classifies_audio_and_video_extensions_case_insensitively(self) -> None:
        self.assertEqual(classify_extension(".M4B"), MediaKind.AUDIOBOOK)
        self.assertEqual(classify_extension(".mkv"), MediaKind.VIDEO)
        self.assertEqual(classify_extension(".txt"), MediaKind.OTHER)

    def test_scan_is_read_only_and_builds_directory_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Brandon Sanderson" / "Warbreaker"
            sibling = root / "Brandon Sanderson" / "Mistborn"
            show = root / "TV" / "DS9 Complete"
            book.mkdir(parents=True)
            sibling.mkdir(parents=True)
            show.mkdir(parents=True)
            (book / "Chapter Thirty-One.mp3").write_bytes(b"abc")
            (book / "cover.jpg").write_bytes(b"image")
            (show / "DS9.1x01.Emissary.mkv").write_bytes(b"video")

            snapshot = scan_library(root)

            self.assertEqual(len(snapshot.files), 2)
            paths = {entry.relative_path for entry in snapshot.files}
            self.assertIn("Brandon Sanderson/Warbreaker/Chapter Thirty-One.mp3", paths)
            self.assertIn("TV/DS9 Complete/DS9.1x01.Emissary.mkv", paths)
            self.assertNotIn("Brandon Sanderson/Warbreaker/cover.jpg", paths)
            self.assertEqual(snapshot.schema_version, 1)
            self.assertTrue(all(entry.mtime_ns is not None for entry in snapshot.files))

            contexts = {context.relative_path: context for context in snapshot.directories}
            self.assertIn("Mistborn", contexts["Brandon Sanderson/Warbreaker"].sibling_names)
            self.assertEqual(
                contexts["Brandon Sanderson/Warbreaker"].file_names,
                ("Chapter Thirty-One.mp3",),
            )

    def test_plan_builds_reverse_order_rollback(self) -> None:
        plan = Plan(
            root="/media",
            operations=(
                FileOperation(
                    kind=OperationKind.MOVE,
                    source="messy/book.m4b",
                    destination="Author/Book/Book.m4b",
                    reason="canonical audiobook layout",
                    confidence=0.99,
                ),
                FileOperation(
                    kind=OperationKind.RENAME,
                    source="tv/DS9.1x01.mkv",
                    destination="tv/Star Trek Deep Space Nine S01E01.mkv",
                    reason="canonical episode name",
                    confidence=0.98,
                ),
            ),
        )

        rollback = plan.rollback_operations
        self.assertEqual(rollback[0].source, "tv/Star Trek Deep Space Nine S01E01.mkv")
        self.assertEqual(rollback[0].destination, "tv/DS9.1x01.mkv")
        self.assertEqual(rollback[1].source, "Author/Book/Book.m4b")
        self.assertEqual(rollback[1].destination, "messy/book.m4b")
        self.assertTrue(plan.reversible)


if __name__ == "__main__":
    unittest.main()
