from __future__ import annotations

import unittest

from media_janitor.audiobookshelf import AudiobookshelfItem
from media_janitor.items import AudiobookItemAnalysis
from media_janitor.matching import (
    match_audiobook_item,
    match_audiobook_items,
    score_audiobookshelf_item,
    text_similarity,
)


def local_item(
    *,
    path: str = "Brandon Sanderson/Mistborn 01 - The Final Empire",
    title: str | None = "The Final Empire",
    authors: tuple[str, ...] = ("Brandon Sanderson",),
    narrators: tuple[str, ...] = ("Michael Kramer",),
    series: str | None = "Mistborn",
    sequence: str | None = "1",
    asin: str | None = None,
    isbn: str | None = None,
    duration: float | None = 24_000.0,
) -> AudiobookItemAnalysis:
    return AudiobookItemAnalysis(
        item_path=path,
        files=(),
        title_hint=title,
        author_hints=authors,
        narrator_hints=narrators,
        series_hint=series,
        series_index_hint=sequence,
        asin=asin,
        isbn=isbn,
        total_duration_seconds=duration,
        confidence=0.8,
        evidence=(),
        warnings=(),
    )


def server_item(
    item_id: str,
    *,
    path: str = "/audiobooks/Brandon Sanderson/Mistborn 01 - The Final Empire",
    title: str | None = "The Final Empire",
    authors: tuple[str, ...] = ("Brandon Sanderson",),
    narrators: tuple[str, ...] = ("Michael Kramer",),
    series: tuple[tuple[str, str | None], ...] = (("Mistborn", "1"),),
    asin: str | None = None,
    isbn: str | None = None,
    duration: float | None = 24_020.0,
) -> AudiobookshelfItem:
    return AudiobookshelfItem(
        id=item_id,
        library_id="lib_1",
        path=path,
        title=title,
        authors=authors,
        narrators=narrators,
        series=series,
        duration_seconds=duration,
        asin=asin,
        isbn=isbn,
    )


class MatchingTests(unittest.TestCase):
    def test_title_similarity_handles_series_prefix_noise(self) -> None:
        self.assertGreaterEqual(
            text_similarity("Mistborn 01 - The Final Empire", "The Final Empire"),
            0.90,
        )

    def test_identifier_match_dominates_similar_title_candidate(self) -> None:
        local = local_item(asin="B002V0QCYU")
        correct = server_item("correct", asin="B002V0QCYU")
        similar = server_item(
            "similar",
            path="/audiobooks/Brandon Sanderson/The Final Empire Alternate",
            asin="WRONGASIN",
            duration=24_010.0,
        )

        result = match_audiobook_item(local, (similar, correct))

        self.assertEqual(result.status, "strong_candidate")
        self.assertEqual(result.best.item.id, "correct")
        self.assertTrue(any(entry.field == "asin" and entry.contribution > 0 for entry in result.best.evidence))

    def test_title_author_duration_and_path_can_make_strong_candidate(self) -> None:
        result = match_audiobook_item(local_item(), (server_item("match"),))

        self.assertEqual(result.status, "strong_candidate")
        self.assertGreaterEqual(result.best.score, 0.72)
        fields = {entry.field for entry in result.best.evidence}
        self.assertTrue({"title", "author", "duration", "path"}.issubset(fields))

    def test_close_candidates_remain_ambiguous(self) -> None:
        local = local_item(series=None, sequence=None, narrators=())
        first = server_item(
            "a",
            path="/library/The Final Empire",
            series=(),
            narrators=(),
            duration=24_020.0,
        )
        second = server_item(
            "b",
            path="/other/The Final Empire",
            series=(),
            narrators=(),
            duration=24_050.0,
        )

        result = match_audiobook_item(local, (first, second))

        self.assertEqual(result.status, "ambiguous")
        self.assertIsNotNone(result.margin)
        self.assertLess(result.margin, 0.12)

    def test_candidate_limit_does_not_hide_close_runner_up(self) -> None:
        local = local_item(series=None, sequence=None, narrators=())
        first = server_item("a", path="/library/The Final Empire", series=(), narrators=())
        second = server_item("b", path="/other/The Final Empire", series=(), narrators=())

        result = match_audiobook_item(local, (first, second), candidate_limit=1)

        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.status, "ambiguous")
        self.assertIsNotNone(result.margin)
        self.assertLess(result.margin, 0.12)

    def test_duplicate_strong_assignment_is_downgraded_for_review(self) -> None:
        server = server_item("same-server-item")
        first = local_item(path="copy-a/The Final Empire")
        second = local_item(path="copy-b/The Final Empire")

        results = match_audiobook_items((first, second), (server,))

        self.assertEqual([result.status for result in results], ["ambiguous", "ambiguous"])
        self.assertTrue(all(result.warnings for result in results))
        self.assertTrue(all("multiple local items" in result.warnings[0] for result in results))

    def test_conflicting_identifier_is_negative_evidence(self) -> None:
        candidate = score_audiobookshelf_item(
            local_item(asin="GOODASIN"),
            server_item("wrong", asin="DIFFERENT"),
        )
        asin_evidence = next(entry for entry in candidate.evidence if entry.field == "asin")
        self.assertLess(asin_evidence.contribution, 0)

    def test_unrelated_item_is_not_presented_as_match(self) -> None:
        unrelated = server_item(
            "other",
            path="/audiobooks/Ursula Le Guin/A Wizard of Earthsea",
            title="A Wizard of Earthsea",
            authors=("Ursula K. Le Guin",),
            narrators=("Rob Inglis",),
            series=(("Earthsea", "1"),),
            duration=18_000.0,
        )

        result = match_audiobook_item(local_item(), (unrelated,))

        self.assertEqual(result.status, "no_candidate")
        self.assertLess(result.best.score, 0.35)


if __name__ == "__main__":
    unittest.main()
