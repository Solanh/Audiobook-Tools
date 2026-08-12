from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from media_janitor.executor import (
    UnsafePlanError,
    _rename_noreplace,
    apply_plan,
    rollback_journal,
    validate_plan,
)
from media_janitor.journal import JournalError, create_journal, load_journal, set_journal_status, set_operation_state
from media_janitor.models import FileOperation, OperationKind, Plan


class ExecutorTests(unittest.TestCase):
    def test_apply_and_rollback_are_journaled_and_reversible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "media"
            state = base / "state"
            root.mkdir()
            state.mkdir()
            source = root / "messy.m4b"
            source.write_bytes(b"book")

            plan = Plan(
                root=str(root),
                operations=(
                    FileOperation(kind=OperationKind.MKDIR, destination="Author", reason="canonical author"),
                    FileOperation(kind=OperationKind.MKDIR, destination="Author/Book", reason="canonical book"),
                    FileOperation(
                        kind=OperationKind.MOVE,
                        source="messy.m4b",
                        destination="Author/Book/Book.m4b",
                        reason="canonical audiobook layout",
                    ),
                ),
            )
            journal_path = state / "journals" / f"{plan.plan_id}.json"

            journal = apply_plan(plan, journal_path, confirmed=True)
            self.assertEqual(journal["status"], "completed")
            self.assertFalse(source.exists())
            self.assertEqual((root / "Author/Book/Book.m4b").read_bytes(), b"book")
            self.assertEqual(
                [record["state"] for record in load_journal(journal_path)["operations"]],
                ["applied", "applied", "applied"],
            )

            rolled_back = rollback_journal(journal_path, confirmed=True)
            self.assertEqual(rolled_back["status"], "rolled_back")
            self.assertEqual(source.read_bytes(), b"book")
            self.assertFalse((root / "Author").exists())
            self.assertEqual(
                [record["state"] for record in load_journal(journal_path)["operations"]],
                ["rolled_back", "rolled_back", "rolled_back"],
            )

    def test_rollback_reconciles_crash_after_rename_before_journal_update(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "media"
            state = base / "state"
            root.mkdir()
            state.mkdir()
            (root / "before.m4b").write_bytes(b"book")

            operation = FileOperation(
                kind=OperationKind.RENAME,
                source="before.m4b",
                destination="after.m4b",
            )
            plan = Plan(root=str(root), operations=(operation,))
            journal_path = state / "crash.json"
            journal = create_journal(plan, journal_path)
            set_journal_status(journal_path, journal, "applying")
            set_operation_state(journal_path, journal, operation.operation_id, "applying")

            # Simulate a process dying after the atomic rename but before it could
            # persist operation=applied.
            (root / "before.m4b").rename(root / "after.m4b")

            rolled_back = rollback_journal(journal_path, confirmed=True)
            self.assertEqual(rolled_back["status"], "rolled_back")
            self.assertTrue((root / "before.m4b").exists())
            self.assertFalse((root / "after.m4b").exists())

    def test_journal_must_live_outside_media_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "media"
            root.mkdir()
            (root / "book.m4b").write_bytes(b"book")
            plan = Plan(
                root=str(root),
                operations=(
                    FileOperation(kind=OperationKind.RENAME, source="book.m4b", destination="Book.m4b"),
                ),
            )

            with self.assertRaises(UnsafePlanError):
                apply_plan(plan, root / "journal.json", confirmed=True)
            self.assertTrue((root / "book.m4b").exists())

    def test_irreversible_metadata_write_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan = Plan(
                root=str(root),
                operations=(FileOperation(kind=OperationKind.WRITE_METADATA, source="book.m4b"),),
            )
            with self.assertRaises(UnsafePlanError):
                validate_plan(plan)

    def test_atomic_rename_never_replaces_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.m4b"
            destination = root / "destination.m4b"
            source.write_bytes(b"source")
            destination.write_bytes(b"destination")

            with self.assertRaises(UnsafePlanError):
                _rename_noreplace(source, destination)

            self.assertEqual(source.read_bytes(), b"source")
            self.assertEqual(destination.read_bytes(), b"destination")

    def test_existing_destination_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "media"
            state = base / "state"
            root.mkdir()
            state.mkdir()
            (root / "before.m4b").write_bytes(b"before")
            (root / "after.m4b").write_bytes(b"after")
            plan = Plan(
                root=str(root),
                operations=(
                    FileOperation(kind=OperationKind.RENAME, source="before.m4b", destination="after.m4b"),
                ),
            )
            journal_path = state / "collision.json"

            with self.assertRaises(UnsafePlanError):
                apply_plan(plan, journal_path, confirmed=True)
            self.assertEqual((root / "before.m4b").read_bytes(), b"before")
            self.assertEqual((root / "after.m4b").read_bytes(), b"after")
            self.assertEqual(load_journal(journal_path)["status"], "failed")

    def test_journal_detects_plan_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "media"
            state = base / "state"
            root.mkdir()
            state.mkdir()
            (root / "book.m4b").write_bytes(b"book")
            plan = Plan(
                root=str(root),
                operations=(FileOperation(kind=OperationKind.RENAME, source="book.m4b", destination="Book.m4b"),),
            )
            journal_path = state / "journal.json"
            create_journal(plan, journal_path)
            payload = json.loads(journal_path.read_text(encoding="utf-8"))
            payload["plan"]["operations"][0]["destination"] = "tampered.m4b"
            journal_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(JournalError):
                load_journal(journal_path)

    def test_symlink_source_is_refused_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "media"
            state = base / "state"
            root.mkdir()
            state.mkdir()
            target = root / "real.m4b"
            target.write_bytes(b"book")
            link = root / "linked.m4b"
            link.symlink_to(target.name)
            plan = Plan(
                root=str(root),
                operations=(
                    FileOperation(kind=OperationKind.RENAME, source="linked.m4b", destination="Book.m4b"),
                ),
            )

            with self.assertRaises(UnsafePlanError):
                apply_plan(plan, state / "symlink.json", confirmed=True)
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_bytes(), b"book")
            self.assertFalse((root / "Book.m4b").exists())

    def test_stale_plan_refuses_changed_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "media"
            state = base / "state"
            root.mkdir()
            state.mkdir()
            source = root / "book.m4b"
            source.write_bytes(b"before")
            stat_result = source.stat()
            operation = FileOperation(
                kind=OperationKind.RENAME,
                source="book.m4b",
                destination="Book.m4b",
                expected_source_size_bytes=stat_result.st_size,
                expected_source_mtime_ns=stat_result.st_mtime_ns,
            )
            plan = Plan(root=str(root), operations=(operation,))
            source.write_bytes(b"changed-content")

            with self.assertRaises(UnsafePlanError):
                apply_plan(plan, state / "stale.json", confirmed=True)
            self.assertTrue(source.exists())
            self.assertFalse((root / "Book.m4b").exists())


if __name__ == "__main__":
    unittest.main()
