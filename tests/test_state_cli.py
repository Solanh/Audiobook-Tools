from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from media_janitor.audiobookshelf import (
    AudiobookshelfLibrary,
    AudiobookshelfMetadataProvider,
    ProviderBookResult,
)
from media_janitor.cli import main
from media_janitor.items import AudiobookItemAnalysis
from media_janitor.state import StateStore


class FakeStateIdentifyClient:
    base_url = "https://abs.example.test"

    def libraries(self):
        return (AudiobookshelfLibrary(id="lib_1", name="Books", media_type="book"),)

    def library_items(self, library_id: str):
        return ()

    def metadata_providers(self):
        return (AudiobookshelfMetadataProvider(value="audible", text="Audible.com"),)

    def search_books(self, provider: str, title: str, author: str | None = None):
        return (
            ProviderBookResult(
                provider="audible",
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


class StateCliTests(unittest.TestCase):
    def test_identify_can_persist_report_and_stage_pending_proposal_without_media_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "media"
            state_dir = Path(temp_dir) / "state"
            root.mkdir()
            book = root / "Warbreaker"
            book.mkdir()
            source = book / "01.mp3"
            source.write_bytes(b"unchanged-media")
            output = Path(temp_dir) / "identify.json"

            local = AudiobookItemAnalysis(
                item_path="Warbreaker",
                files=(),
                title_hint="Warbreaker",
                author_hints=("Brandon Sanderson",),
                narrator_hints=("Alyssa Bresnahan",),
                series_hint=None,
                series_index_hint=None,
                asin="B00WARBREAKER",
                isbn=None,
                total_duration_seconds=44_000.0,
                confidence=0.99,
                evidence=("synthetic",),
                warnings=(),
            )

            with patch("media_janitor.cli.client_from_environment", return_value=FakeStateIdentifyClient()):
                with patch("media_janitor.cli.analyze_audiobook_items", return_value=(local,)):
                    with redirect_stdout(StringIO()):
                        result = main(
                            [
                                "identify-audiobooks",
                                str(root),
                                "--state-dir",
                                str(state_dir),
                                "--stage-strong-proposals",
                                "--json",
                                str(output),
                                "--pretty",
                            ]
                        )

            self.assertEqual(result, 0)
            self.assertEqual(source.read_bytes(), b"unchanged-media")

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertIsNotNone(payload["state"])
            self.assertEqual(len(payload["state"]["staged_proposal_ids"]), 1)

            store = StateStore.from_state_dir(state_dir)
            summary = store.summary()
            self.assertEqual(summary["reports"], 1)
            self.assertEqual(summary["proposals"], {"pending": 1})
            proposal = store.list_proposals(status="pending")[0]
            self.assertEqual(proposal.local_item_path, "Warbreaker")
            self.assertEqual(proposal.candidate["selected_candidate"]["provider_result"]["asin"], "B00WARBREAKER")

    def test_proposal_decision_changes_only_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"
            media = Path(temp_dir) / "book.m4b"
            media.write_bytes(b"media")
            store = StateStore.from_state_dir(state_dir)
            report = store.save_report("identify-audiobooks", {"records": []})
            proposal = store.stage_proposal(report.report_id, "Book", {"candidate": {"title": "Book"}})

            with redirect_stdout(StringIO()):
                result = main(
                    [
                        "proposal-decide",
                        proposal.proposal_id,
                        "--state-dir",
                        str(state_dir),
                        "--decision",
                        "approved",
                        "--note",
                        "human reviewed",
                    ]
                )

            self.assertEqual(result, 0)
            self.assertEqual(media.read_bytes(), b"media")
            decided = store.get_proposal(proposal.proposal_id)
            self.assertEqual(decided.status, "approved")
            self.assertEqual(decided.decision_note, "human reviewed")

    def test_state_database_is_rejected_inside_media_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "media"
            root.mkdir()
            book = root / "Book"
            book.mkdir()
            (book / "01.mp3").write_bytes(b"audio")
            state_dir = root / ".media-janitor-state"

            with patch("media_janitor.cli.client_from_environment", return_value=FakeStateIdentifyClient()):
                with self.assertRaises(SystemExit) as error:
                    with redirect_stdout(StringIO()):
                        main(
                            [
                                "identify-audiobooks",
                                str(root),
                                "--state-dir",
                                str(state_dir),
                                "--max-provider-searches",
                                "1",
                            ]
                        )

            self.assertEqual(error.exception.code, 1)
            self.assertFalse(state_dir.exists())

    def test_state_status_and_audit_list_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"
            with redirect_stdout(StringIO()) as stdout:
                result = main(["state-init", "--state-dir", str(state_dir)])
            self.assertEqual(result, 0)
            init_payload = json.loads(stdout.getvalue())
            self.assertEqual(init_payload["reports"], 0)

            store = StateStore.from_state_dir(state_dir)
            store.save_report("test", {"ok": True}, report_id="r1")

            with redirect_stdout(StringIO()) as stdout:
                result = main(["audit-list", "--state-dir", str(state_dir), "--limit", "10"])
            self.assertEqual(result, 0)
            self.assertIn("report_saved", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
