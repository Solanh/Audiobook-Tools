from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from media_janitor.state import StateError, StateStore, state_database_path


class StateStoreTests(unittest.TestCase):
    def test_initializes_state_database_and_reports_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = StateStore.from_state_dir(temp_dir)
            store.initialize()

            self.assertEqual(store.path, state_database_path(temp_dir))
            self.assertTrue(store.path.exists())
            summary = store.summary()
            self.assertEqual(summary["schema_version"], 1)
            self.assertEqual(summary["reports"], 0)
            self.assertEqual(summary["proposals"], {})
            self.assertEqual(summary["audit_events"], 0)

    def test_saved_reports_are_content_hashed_and_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = StateStore.from_state_dir(temp_dir)
            payload = {"root": "/media", "matches": [{"status": "ambiguous"}]}
            report = store.save_report(
                "audiobookshelf-match",
                payload,
                root="/media",
                report_id="report-1",
            )

            loaded = store.get_report("report-1")
            self.assertEqual(loaded.payload, payload)
            self.assertEqual(loaded.payload_sha256, report.payload_sha256)

            same = store.save_report(
                "audiobookshelf-match",
                payload,
                root="/media",
                report_id="report-1",
            )
            self.assertEqual(same.payload_sha256, report.payload_sha256)

            with self.assertRaises(StateError):
                store.save_report(
                    "audiobookshelf-match",
                    {"root": "/different"},
                    report_id="report-1",
                )

    def test_report_integrity_check_detects_direct_database_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = StateStore.from_state_dir(temp_dir)
            store.save_report("identify-audiobooks", {"value": 1}, report_id="report-1")

            with sqlite3.connect(store.path) as connection:
                connection.execute(
                    "UPDATE reports SET payload_json = ? WHERE report_id = ?",
                    ('{"value":2}', "report-1"),
                )

            with self.assertRaisesRegex(StateError, "integrity verification"):
                store.get_report("report-1")

    def test_proposal_lifecycle_is_pending_then_one_immutable_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = StateStore.from_state_dir(temp_dir)
            store.save_report(
                "identify-audiobooks",
                {"records": []},
                report_id="report-1",
            )
            candidate = {
                "provider": "audible",
                "identity_score": 0.94,
                "edition_score": 0.87,
                "provider_result": {"title": "Warbreaker", "asin": "B00EXAMPLE"},
            }

            proposal = store.stage_proposal(
                "report-1",
                "Warbreaker",
                candidate,
                proposal_id="proposal-1",
            )
            self.assertEqual(proposal.status, "pending")

            duplicate = store.stage_proposal(
                "report-1",
                "Warbreaker",
                candidate,
                proposal_id="ignored-new-id",
            )
            self.assertEqual(duplicate.proposal_id, "proposal-1")

            decided = store.decide_proposal("proposal-1", "approved", note="reviewed metadata only")
            self.assertEqual(decided.status, "approved")
            self.assertEqual(decided.decision_note, "reviewed metadata only")

            with self.assertRaisesRegex(StateError, "decisions are immutable"):
                store.decide_proposal("proposal-1", "rejected", note="changed mind")

            events = store.list_audit_events(entity_type="proposal", entity_id="proposal-1")
            self.assertEqual([event.event_type for event in reversed(events)], ["proposal_staged", "proposal_decided"])

    def test_cannot_stage_proposal_from_missing_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = StateStore.from_state_dir(temp_dir)
            with self.assertRaisesRegex(StateError, "missing report"):
                store.stage_proposal(
                    "does-not-exist",
                    "Book",
                    {"candidate": "x"},
                )

    def test_lists_pending_proposals_separately(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = StateStore.from_state_dir(temp_dir)
            store.save_report("identify-audiobooks", {"records": []}, report_id="report-1")
            first = store.stage_proposal("report-1", "Book One", {"title": "Book One"})
            second = store.stage_proposal("report-1", "Book Two", {"title": "Book Two"})
            store.decide_proposal(first.proposal_id, "ignored")

            pending = store.list_proposals(status="pending")
            self.assertEqual([proposal.proposal_id for proposal in pending], [second.proposal_id])


if __name__ == "__main__":
    unittest.main()
