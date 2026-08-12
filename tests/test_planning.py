from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from media_janitor.models import OperationKind
from media_janitor.planning import DraftPlanError, build_draft_plan, canonical_item_path
from media_janitor.state import StateStore


class DraftPlanningTests(unittest.TestCase):
    def _stage_proposal(
        self,
        root: Path,
        *,
        item_path: str = "Incoming/The Final Empire",
        source_files: tuple[str, ...] = ("Incoming/The Final Empire/01.mp3", "Incoming/The Final Empire/02.mp3"),
        title: str = "The Final Empire",
        authors: tuple[str, ...] = ("Brandon Sanderson",),
        series: tuple[tuple[str, str | None], ...] = (("Mistborn", "1"),),
        approved: bool = True,
    ):
        store = StateStore.from_state_dir(root.parent / "state")
        file_records = []
        for relative in source_files:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("audio:" + relative).encode("utf-8"))
            stat = path.stat()
            file_records.append(
                {
                    "path": relative,
                    "size_bytes": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "normalized_name": path.name,
                    "chapter_hint": None,
                    "embedded": None,
                    "metadata_error": None,
                }
            )

        report = store.save_report(
            "identify-audiobooks",
            {"root": str(root), "records": []},
            root=str(root),
        )
        provider_series = [
            {"name": name, "sequence": sequence}
            for name, sequence in series
        ]
        candidate = {
            "current_server_match": {
                "status": "ambiguous",
                "local_item": {
                    "item_path": item_path,
                    "file_count": len(file_records),
                    "title_hint": title,
                    "author_hints": list(authors),
                    "narrator_hints": [],
                    "series_hint": series[0][0] if series else None,
                    "series_index_hint": series[0][1] if series else None,
                    "identifiers": {"asin": None, "isbn": None},
                    "total_duration_seconds": None,
                    "confidence": 0.8,
                    "evidence": [],
                    "warnings": [],
                    "files": file_records,
                },
                "candidates": [],
            },
            "provider_match": {
                "provider": "audible",
                "status": "strong_identity_candidate",
                "warnings": [],
            },
            "selected_candidate": {
                "identity_score": 0.96,
                "edition_score": 0.91,
                "provider_result": {
                    "provider": "audible",
                    "provider_id": "B002V0QCYU",
                    "title": title,
                    "authors": list(authors),
                    "narrators": ["Michael Kramer"],
                    "series": provider_series,
                    "asin": "B002V0QCYU",
                    "isbn": None,
                },
                "evidence": [],
            },
        }
        proposal = store.stage_proposal(report.report_id, item_path, candidate)
        if approved:
            proposal = store.decide_proposal(proposal.proposal_id, "approved", note="reviewed")
        return store, proposal

    def test_author_series_layout_generates_fingerprinted_file_moves_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "media"
            root.mkdir()
            store, proposal = self._stage_proposal(root)
            cover = root / "Incoming/The Final Empire/cover.jpg"
            cover.write_bytes(b"cover")
            original_audio = (root / "Incoming/The Final Empire/01.mp3").read_bytes()

            result = build_draft_plan(store, proposal.proposal_id, layout="author-series-title")

            self.assertEqual(result.target_item_path, "Brandon Sanderson/Mistborn/01 - The Final Empire")
            self.assertEqual(result.companion_files, ("Incoming/The Final Empire/cover.jpg",))
            self.assertEqual((root / "Incoming/The Final Empire/01.mp3").read_bytes(), original_audio)
            self.assertTrue(cover.exists())
            self.assertFalse((root / result.target_item_path).exists())

            moves = [operation for operation in result.plan.operations if operation.kind is OperationKind.MOVE]
            self.assertEqual(len(moves), 3)
            self.assertTrue(all(operation.expected_source_size_bytes is not None for operation in moves))
            self.assertTrue(all(operation.expected_source_mtime_ns is not None for operation in moves))
            destinations = {operation.destination for operation in moves}
            self.assertIn("Brandon Sanderson/Mistborn/01 - The Final Empire/01.mp3", destinations)
            self.assertIn("Brandon Sanderson/Mistborn/01 - The Final Empire/cover.jpg", destinations)

    def test_unapproved_proposal_cannot_generate_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "media"
            root.mkdir()
            store, proposal = self._stage_proposal(root, approved=False)

            with self.assertRaisesRegex(DraftPlanError, "only explicitly approved"):
                build_draft_plan(store, proposal.proposal_id)

    def test_extra_unapproved_audio_in_item_tree_blocks_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "media"
            root.mkdir()
            store, proposal = self._stage_proposal(root)
            extra = root / "Incoming/The Final Empire/bonus-or-other-book.mp3"
            extra.write_bytes(b"unexpected audio")

            with self.assertRaisesRegex(DraftPlanError, "Unapproved audio file"):
                build_draft_plan(store, proposal.proposal_id)

    def test_stale_source_fingerprint_blocks_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "media"
            root.mkdir()
            store, proposal = self._stage_proposal(root)
            source = root / "Incoming/The Final Empire/01.mp3"
            source.write_bytes(b"changed after approval")

            with self.assertRaisesRegex(DraftPlanError, "fingerprint is stale"):
                build_draft_plan(store, proposal.proposal_id)

    def test_destination_collision_blocks_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "media"
            root.mkdir()
            store, proposal = self._stage_proposal(root)
            collision = root / "Brandon Sanderson/Mistborn/01 - The Final Empire/01.mp3"
            collision.parent.mkdir(parents=True)
            collision.write_bytes(b"existing")

            with self.assertRaisesRegex(DraftPlanError, "destination already exists"):
                build_draft_plan(store, proposal.proposal_id)

    def test_layout_sanitizes_provider_path_components(self) -> None:
        path = canonical_item_path(
            {
                "title": 'A/B: A "Book"?',
                "authors": ["Author/Name"],
                "series": [{"name": "Series:Name", "sequence": "2"}],
            },
            layout="author-series-title",
        )
        self.assertNotIn('"', path)
        self.assertNotIn(":", path)
        self.assertEqual(path.count("/"), 2)
        self.assertTrue(path.endswith("02 - A - B - A - Book"))

    def test_root_level_item_does_not_absorb_unrelated_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "media"
            root.mkdir()
            store, proposal = self._stage_proposal(
                root,
                item_path=".",
                source_files=("Warbreaker.m4b",),
                title="Warbreaker",
                authors=("Brandon Sanderson",),
                series=(),
            )
            (root / "unrelated.txt").write_text("leave me", encoding="utf-8")

            result = build_draft_plan(store, proposal.proposal_id, layout="author-title")
            moves = [operation for operation in result.plan.operations if operation.kind is OperationKind.MOVE]
            self.assertEqual([operation.source for operation in moves], ["Warbreaker.m4b"])
            self.assertTrue((root / "unrelated.txt").exists())


if __name__ == "__main__":
    unittest.main()
