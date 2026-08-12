from __future__ import annotations

import unittest

from media_janitor.audiobook import ChapterKind, extract_chapter_hint, normalize_search_text, parse_number_words


class AudiobookParsingTests(unittest.TestCase):
    def test_parses_written_chapter_number(self) -> None:
        hint = extract_chapter_hint("Chapter Thirty-One - Warbreaker - Brandon Sanderson.mp3")
        self.assertIsNotNone(hint)
        assert hint is not None
        self.assertEqual(hint.kind, ChapterKind.CHAPTER)
        self.assertEqual(hint.number, 31)

    def test_parses_hundreds_without_old_script_special_case(self) -> None:
        self.assertEqual(parse_number_words("one hundred one"), 101)
        self.assertEqual(parse_number_words("two hundred and forty three"), 243)

    def test_detects_special_sections_without_fake_numeric_order(self) -> None:
        hint = extract_chapter_hint("Epilogue - The End.mp3")
        self.assertIsNotNone(hint)
        assert hint is not None
        self.assertEqual(hint.kind, ChapterKind.EPILOGUE)
        self.assertIsNone(hint.number)

    def test_normalization_records_what_it_removed(self) -> None:
        result = normalize_search_text("The.Way.of.Kings_[Unabridged]_64kbps.m4b")
        self.assertEqual(result.normalized, "The Way of Kings")
        self.assertIn("removed unabridged marker", result.transformations)
        self.assertIn("removed bitrate marker", result.transformations)


if __name__ == "__main__":
    unittest.main()
