from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from media_janitor.items import analyze_audiobook_items
from media_janitor.metadata import EmbeddedAudioMetadata, MetadataReadResult
from media_janitor.scanner import scan_library


class ItemAnalysisTests(unittest.TestCase):
    def test_disc_directories_group_into_one_book(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Brandon Sanderson" / "Mistborn 01 - The Final Empire"
            disc1 = book / "Disc 1"
            disc2 = book / "Disc 2"
            disc1.mkdir(parents=True)
            disc2.mkdir(parents=True)
            (disc1 / "Chapter 01.mp3").write_bytes(b"a")
            (disc2 / "Chapter 02.mp3").write_bytes(b"b")

            def metadata_reader(path: str | Path) -> MetadataReadResult:
                return MetadataReadResult(
                    metadata=EmbeddedAudioMetadata(
                        title=Path(path).stem,
                        album="The Final Empire",
                        album_artists=("Brandon Sanderson",),
                        narrators=("Michael Kramer",),
                        series="Mistborn",
                        series_index="1",
                        asin="B002V0QCYU",
                        duration_seconds=60.0,
                    )
                )

            snapshot = scan_library(root)
            items = analyze_audiobook_items(root, snapshot=snapshot, metadata_reader=metadata_reader)

            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertEqual(item.item_path, "Brandon Sanderson/Mistborn 01 - The Final Empire")
            self.assertEqual(len(item.files), 2)
            self.assertEqual(item.title_hint, "The Final Empire")
            self.assertEqual(item.author_hints[0], "Brandon Sanderson")
            self.assertEqual(item.narrator_hints, ("Michael Kramer",))
            self.assertEqual(item.series_hint, "Mistborn")
            self.assertEqual(item.series_index_hint, "1")
            self.assertEqual(item.asin, "B002V0QCYU")
            self.assertEqual(item.total_duration_seconds, 120.0)
            self.assertGreaterEqual(item.confidence, 0.9)

    def test_conflicting_album_metadata_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Messy Book"
            book.mkdir()
            first = book / "01.mp3"
            second = book / "02.mp3"
            first.write_bytes(b"a")
            second.write_bytes(b"b")

            def metadata_reader(path: str | Path) -> MetadataReadResult:
                album = "Book One" if Path(path).name == "01.mp3" else "Book Two"
                return MetadataReadResult(metadata=EmbeddedAudioMetadata(album=album))

            items = analyze_audiobook_items(root, metadata_reader=metadata_reader)
            self.assertEqual(len(items), 1)
            self.assertTrue(any("conflicting embedded album" in warning for warning in items[0].warnings))

    def test_bad_metadata_does_not_abort_read_only_item_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Fallback Title"
            book.mkdir()
            source = book / "Chapter One.mp3"
            source.write_bytes(b"not-real-audio")

            def metadata_reader(path: str | Path) -> MetadataReadResult:
                return MetadataReadResult(metadata=None, error="invalid audio")

            items = analyze_audiobook_items(root, metadata_reader=metadata_reader)
            self.assertEqual(items[0].title_hint, "Fallback Title")
            self.assertTrue(any("metadata unreadable" in warning for warning in items[0].warnings))
            self.assertTrue(source.exists())


if __name__ == "__main__":
    unittest.main()
