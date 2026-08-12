from __future__ import annotations

import unittest

from media_janitor.audiobookshelf import AudiobookshelfClient, normalize_item, normalize_library


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


if __name__ == "__main__":
    unittest.main()
