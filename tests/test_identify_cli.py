from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from media_janitor.audiobookshelf import (
    AudiobookshelfItem,
    AudiobookshelfLibrary,
    AudiobookshelfMetadataProvider,
    ProviderBookResult,
)
from media_janitor.cli import main


class FakeIdentifyClient:
    base_url = "https://abs.example.test"

    def __init__(self, *, strong_existing_match: bool = False) -> None:
        self.strong_existing_match = strong_existing_match
        self.search_calls: list[tuple[str, str, str | None]] = []

    def libraries(self):
        return (AudiobookshelfLibrary(id="lib_1", name="Books", media_type="book"),)

    def library_items(self, library_id: str):
        if not self.strong_existing_match:
            return ()
        return (
            AudiobookshelfItem(
                id="li_warbreaker",
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

    def metadata_providers(self):
        return (
            AudiobookshelfMetadataProvider(value="audible", text="Audible.com"),
            AudiobookshelfMetadataProvider(value="google", text="Google Books"),
        )

    def search_books(self, provider: str, title: str, author: str | None = None):
        self.search_calls.append((provider, title, author))
        return (
            ProviderBookResult(
                provider=provider,
                provider_id="B00WARBREAKER",
                title="Warbreaker",
                subtitle=None,
                authors=("Brandon Sanderson",),
                narrators=("Alyssa Bresnahan",),
                series=(),
                duration_seconds=44_000.0,
                asin="B00WARBREAKER",
                isbn=None,
                language="English",
                publisher=None,
                published_year=None,
                abridged=False,
                cover=None,
            ),
        )


class IdentifyCliTests(unittest.TestCase):
    def _build_tagless_book(self, root: Path) -> Path:
        book = root / "Warbreaker"
        book.mkdir()
        source = book / "Chapter One.mp3"
        source.write_bytes(b"synthetic-tagless-audio")
        return source

    def test_unresolved_item_is_searched_read_only_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = self._build_tagless_book(root)
            output = root / "identify.json"
            client = FakeIdentifyClient()

            stdout = StringIO()
            with patch("media_janitor.cli.client_from_environment", return_value=client):
                with redirect_stdout(stdout):
                    result = main(
                        [
                            "identify-audiobooks",
                            str(root),
                            "--provider",
                            "audible",
                            "--max-provider-searches",
                            "1",
                            "--json",
                            str(output),
                            "--pretty",
                        ]
                    )

            self.assertEqual(result, 0)
            self.assertEqual(source.read_bytes(), b"synthetic-tagless-audio")
            self.assertEqual(client.search_calls, [("audible", "Warbreaker", None)])

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["provider_searches"], 1)
            self.assertEqual(payload["records"][0]["local_item_path"], "Warbreaker")
            provider_search = payload["records"][0]["provider_search"]
            self.assertEqual(provider_search["provider"], "audible")
            self.assertEqual(provider_search["candidates"][0]["provider_result"]["title"], "Warbreaker")

    def test_strong_existing_server_match_skips_provider_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = self._build_tagless_book(root)
            output = root / "identify.json"
            client = FakeIdentifyClient(strong_existing_match=True)

            with patch("media_janitor.cli.client_from_environment", return_value=client):
                with redirect_stdout(StringIO()):
                    result = main(
                        [
                            "identify-audiobooks",
                            str(root),
                            "--json",
                            str(output),
                            "--pretty",
                        ]
                    )

            self.assertEqual(result, 0)
            self.assertTrue(source.exists())
            self.assertEqual(client.search_calls, [])
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["strong_current_server_matches"], 1)
            self.assertEqual(payload["unresolved_items"], 0)
            self.assertEqual(payload["records"], [])

    def test_provider_search_cap_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in ("Book One", "Book Two"):
                book = root / name
                book.mkdir()
                (book / "01.mp3").write_bytes(b"fixture")
            output = root / "identify.json"
            client = FakeIdentifyClient()

            with patch("media_janitor.cli.client_from_environment", return_value=client):
                with redirect_stdout(StringIO()):
                    result = main(
                        [
                            "identify-audiobooks",
                            str(root),
                            "--max-provider-searches",
                            "1",
                            "--json",
                            str(output),
                        ]
                    )

            self.assertEqual(result, 0)
            self.assertEqual(len(client.search_calls), 1)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["provider_searches"], 1)
            self.assertEqual(payload["provider_searches_skipped"], 1)
            self.assertTrue(
                any(record["provider_search_skipped_reason"] == "provider-search cap reached" for record in payload["records"])
            )


if __name__ == "__main__":
    unittest.main()
