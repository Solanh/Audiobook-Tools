from __future__ import annotations

import unittest

from media_janitor.audiobookshelf import ProviderBookResult
from media_janitor.items import AudiobookItemAnalysis
from media_janitor.provider_matching import rank_provider_results, score_provider_result


def local_item(
    *,
    title: str = "The Final Empire",
    authors: tuple[str, ...] = ("Brandon Sanderson",),
    narrators: tuple[str, ...] = ("Michael Kramer",),
    series: str | None = "Mistborn",
    sequence: str | None = "1",
    asin: str | None = None,
    isbn: str | None = None,
    duration: float | None = 24_000.0,
) -> AudiobookItemAnalysis:
    return AudiobookItemAnalysis(
        item_path="Brandon Sanderson/Mistborn 01 - The Final Empire",
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


def provider_result(
    provider_id: str,
    *,
    provider: str = "audible",
    title: str = "The Final Empire",
    authors: tuple[str, ...] = ("Brandon Sanderson",),
    narrators: tuple[str, ...] = ("Michael Kramer",),
    series: tuple[tuple[str, str | None], ...] = (("Mistborn", "1"),),
    duration: float | None = 24_020.0,
    asin: str | None = None,
    isbn: str | None = None,
) -> ProviderBookResult:
    return ProviderBookResult(
        provider=provider,
        provider_id=provider_id,
        title=title,
        subtitle=None,
        authors=authors,
        narrators=narrators,
        series=series,
        duration_seconds=duration,
        asin=asin,
        isbn=isbn,
        language="English",
        publisher=None,
        published_year=None,
        abridged=False if provider.startswith("audible") else None,
        cover=None,
    )


class ProviderMatchingTests(unittest.TestCase):
    def test_identity_and_edition_are_separate_scores(self) -> None:
        score = score_provider_result(
            local_item(asin="B002V0QCYU"),
            provider_result("B002V0QCYU", asin="B002V0QCYU"),
        )

        self.assertGreaterEqual(score.identity_score, 0.9)
        self.assertIsNotNone(score.edition_score)
        self.assertGreaterEqual(score.edition_score, 0.9)
        dimensions = {entry.dimension for entry in score.evidence}
        self.assertEqual(dimensions, {"identity", "edition"})

    def test_google_like_book_hit_can_have_identity_without_edition_confidence(self) -> None:
        result = provider_result(
            "google-id",
            provider="google",
            narrators=(),
            series=(),
            duration=None,
        )
        ranked = rank_provider_results(
            local_item(narrators=(), series=None, sequence=None, duration=None),
            "google",
            (result,),
        )

        self.assertEqual(ranked.status, "ambiguous")
        self.assertIsNone(ranked.best.edition_score)

    def test_exact_isbn_can_make_book_identity_strong_without_audio_edition_proof(self) -> None:
        result = provider_result(
            "google-id",
            provider="google",
            narrators=(),
            series=(),
            duration=None,
            isbn="9780765311788",
        )
        ranked = rank_provider_results(
            local_item(
                narrators=(),
                series=None,
                sequence=None,
                duration=None,
                isbn="9780765311788",
            ),
            "google",
            (result,),
        )

        self.assertEqual(ranked.status, "strong_identity_candidate")
        self.assertIsNotNone(ranked.best.edition_score)
        self.assertIn("audiobook-edition evidence", ranked.warnings[0])

    def test_close_provider_results_remain_ambiguous(self) -> None:
        first = provider_result("a", duration=24_010.0)
        second = provider_result("b", duration=24_030.0)
        ranked = rank_provider_results(local_item(), "audible", (first, second), candidate_limit=1)

        self.assertEqual(len(ranked.candidates), 1)
        self.assertEqual(ranked.status, "ambiguous")
        self.assertIsNotNone(ranked.identity_margin)
        self.assertLess(ranked.identity_margin, 0.12)

    def test_identifier_conflict_cannot_be_hidden_by_fuzzy_similarity(self) -> None:
        wrong = provider_result("wrong", asin="WRONGASIN")
        score = score_provider_result(local_item(asin="GOODASIN"), wrong)
        asin_evidence = next(
            entry for entry in score.evidence if entry.dimension == "identity" and entry.field == "asin"
        )
        self.assertLess(asin_evidence.contribution, 0)
        self.assertLess(score.identity_score, 0.78)


if __name__ == "__main__":
    unittest.main()
