from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from media_janitor.draft_cli import main
from media_janitor.state import StateStore


class DraftCliTests(unittest.TestCase):
    def _approved_proposal(self, base: Path):
        media = base / "media"
        state = base / "state"
        source = media / "Incoming/Warbreaker/Warbreaker.m4b"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"media-bytes")
        stat = source.stat()

        store = StateStore.from_state_dir(state)
        report = store.save_report(
            "identify-audiobooks",
            {"root": str(media), "records": []},
            root=str(media),
        )
        proposal = store.stage_proposal(
            report.report_id,
            "Incoming/Warbreaker",
            {
                "current_server_match": {
                    "status": "ambiguous",
                    "local_item": {
                        "item_path": "Incoming/Warbreaker",
                        "files": [
                            {
                                "path": "Incoming/Warbreaker/Warbreaker.m4b",
                                "size_bytes": stat.st_size,
                                "mtime_ns": stat.st_mtime_ns,
                            }
                        ],
                    },
                },
                "provider_match": {
                    "provider": "audible",
                    "status": "strong_identity_candidate",
                    "warnings": [],
                },
                "selected_candidate": {
                    "identity_score": 0.97,
                    "edition_score": 0.92,
                    "provider_result": {
                        "provider": "audible",
                        "title": "Warbreaker",
                        "authors": ["Brandon Sanderson"],
                        "narrators": ["Alyssa Bresnahan"],
                        "series": [],
                        "asin": "B00EXAMPLE",
                        "isbn": None,
                    },
                    "evidence": [],
                },
            },
        )
        proposal = store.decide_proposal(proposal.proposal_id, "approved", note="reviewed")
        return media, state, source, store, proposal

    def test_command_writes_validated_draft_outside_media_without_applying(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            media, state, source, store, proposal = self._approved_proposal(base)
            stdout = StringIO()

            with redirect_stdout(stdout):
                result = main(
                    [
                        proposal.proposal_id,
                        "--state-dir",
                        str(state),
                        "--layout",
                        "author-title",
                        "--pretty",
                    ]
                )

            self.assertEqual(result, 0)
            summary = json.loads(stdout.getvalue())
            self.assertFalse(summary["apply_performed"])
            self.assertEqual(summary["target_item_path"], "Brandon Sanderson/Warbreaker")
            plan_path = Path(summary["plan_file"])
            self.assertTrue(plan_path.exists())
            self.assertTrue(plan_path.is_relative_to(state))
            self.assertFalse(plan_path.is_relative_to(media))
            self.assertEqual(source.read_bytes(), b"media-bytes")
            self.assertFalse((media / "Brandon Sanderson/Warbreaker/Warbreaker.m4b").exists())

            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertTrue(plan["reversible"])
            self.assertTrue(any(op["kind"] == "move" for op in plan["operations"]))
            reports = store.list_reports(kind="draft-plan")
            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0].payload["proposal_id"], proposal.proposal_id)

    def test_command_refuses_plan_output_inside_media_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            media, state, source, _, proposal = self._approved_proposal(base)
            output = media / "dangerous-plan.json"

            with self.assertRaises(SystemExit) as caught:
                with redirect_stdout(StringIO()):
                    main(
                        [
                            proposal.proposal_id,
                            "--state-dir",
                            str(state),
                            "--output",
                            str(output),
                        ]
                    )

            self.assertEqual(caught.exception.code, 1)
            self.assertFalse(output.exists())
            self.assertTrue(source.exists())

    def test_command_refuses_overwriting_existing_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            _, state, source, _, proposal = self._approved_proposal(base)
            output = state / "plans/custom.json"
            output.parent.mkdir(parents=True)
            output.write_text("do not replace", encoding="utf-8")

            with self.assertRaises(SystemExit) as caught:
                with redirect_stdout(StringIO()):
                    main(
                        [
                            proposal.proposal_id,
                            "--state-dir",
                            str(state),
                            "--output",
                            str(output),
                        ]
                    )

            self.assertEqual(caught.exception.code, 1)
            self.assertEqual(output.read_text(encoding="utf-8"), "do not replace")
            self.assertTrue(source.exists())


if __name__ == "__main__":
    unittest.main()
