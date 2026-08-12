from __future__ import annotations

import unittest

from media_janitor.audiobookshelf import (
    AudiobookshelfClient,
    normalize_item,
    normalize_library,
    normalize_metadata_provider,
    normalize_provider_book,
)


class FakeProviderClient(AudiobookshelfClient):
    def __init__(self) -> None:
        super().__init__("https://example.test/audiobookshelf", "secret")
        self.requests: list[tuple[str, dict[str, object] | None]] = []

    def _get_json(self, path: str, query: dict[str, object] | None = None):
        self.requests.append((path, query))
        if path == "api/search/providers":
            return {
                "providers": {
                    "books": [
                        {"value": "google", "text": "Google Books"},
                        {"value": "audible", "text": "Audible.com"},
                    ]
                }
            }
        if path == "api/search/books":
            return [
                {
                    "title": "The Final Empire",
                    "author": "Brandon Sanderson",
                    "asin": "B002V0QCYU",
                    "duration": 401.5,
                }
            ]
        raise AssertionError(f"unexpected path: {path}")


class AudiobookshelfTests(unittest.TestCase):
    def test_client_preserves_reverse_proxy_subpath(self) -> None:
        client = AudiobookshelfClient("https://example.test/audiobookshelf", "secret")
        self.assertEqual(
            client._url("api/libraries"),
            "https://example.test/audiobookshelf/api/libraries",
        )

    def test_normalizes_library(self) -> None:
        library = normalize_library({"id": "lib_1", "name": "Audiobooks", "mediaType": "book"})
        self.assertEqual(library.id, "lib_1")
        self.assertEqual(library.name, "Audiobooks")
        self.assertEqual(library.media_type, "book")

    def test_normalizes_book_item_across_common_response_shapes(self) -> None:
        item = normalize_item(
            {
                "id": "li_1",
                "libraryId": "lib_1",
                "path": "/audiobooks/Brandon Sanderson/The Final Empire",
                "media": {
                    "duration": 12345.5,
                    "metadata": {
                        "title": "The Final Empire",
                        "authors": [{"name": "Brandon Sanderson"}],
                        "narrators": ["Michael Kramer"],
                        "series": [{"name": "Mistborn", "sequence": "1"}],
                        "asin": "B002V0QCYU",
                        "isbn": "9780765311788",
                    },
                },
            }
        )

        self.assertEqual(item.title, "The Final Empire")
        self.assertEqual(item.authors, ("Brandon Sanderson",))
        self.assertEqual(item.narrators, ("Michael Kramer",))
        self.assertEqual(item.series, (("Mistborn", "1"),))
        self.assertEqual(item.duration_seconds, 12345.5)
        self.assertEqual(item.asin, "B002V0QCYU")
        self.assertEqual(item.isbn, "9780765311788")

    def test_normalizes_metadata_provider(self) -> None:
        provider = normalize_metadata_provider({"value": "audible", "text": "Audible.com"})
        self.assertEqual(provider.value, "audible")
        self.assertEqual(provider.text, "Audible.com")

    def test_normalizes_audible_result_and_converts_minutes_to_seconds(self) -> None:
        result = normalize_provider_book(
            "audible",
            {
                "title": "The Final Empire",
                "subtitle": "Mistborn, Book 1",
                "author": "Brandon Sanderson",
                "narrator": "Michael Kramer",
                "series": [{"series": "Mistborn", "sequence": "1"}],
                "duration": 401.5,
                "asin": "B002V0QCYU",
                "isbn": "9780765311788",
                "language": "English",
                "publisher": "Macmillan Audio",
                "publishedYear": "2009",
                "abridged": False,
            },
        )

        self.assertEqual(result.provider_id, "B002V0QCYU")
        self.assertEqual(result.authors, ("Brandon Sanderson",))
        self.assertEqual(result.narrators, ("Michael Kramer",))
        self.assertEqual(result.series, (("Mistborn", "1"),))
        self.assertEqual(result.duration_seconds, 24_090.0)
        self.assertFalse(result.abridged)

    def test_normalizes_google_result_without_assuming_audiobook_fields(self) -> None:
        result = normalize_provider_book(
            "google",
            {
                "id": "google-id",
                "title": "The Final Empire",
                "author": "Brandon Sanderson",
                "isbn": "9780765311788",
                "publishedYear": "2006",
            },
        )

        self.assertEqual(result.provider_id, "google-id")
        self.assertEqual(result.isbn, "9780765311788")
        self.assertIsNone(result.duration_seconds)
        self.assertEqual(result.narrators, ())
        self.assertEqual(result.series, ())

    def test_provider_discovery_and_search_are_get_style_read_calls(self) -> None:
        client = FakeProviderClient()
        providers = client.metadata_providers()
        results = client.search_books("audible", "The Final Empire", "Brandon Sanderson")

        self.assertEqual([provider.value for provider in providers], ["google", "audible"])
        self.assertEqual(results[0].asin, "B002V0QCYU")
        self.assertEqual(
            client.requests[-1],
            (
                "api/search/books",
                {
                    "provider": "audible",
                    "title": "The Final Empire",
                    "author": "Brandon Sanderson",
                },
            ),
        )


if __name__ == "__main__":
    unittest.main()
