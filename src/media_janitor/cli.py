from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Sequence

from .audiobook import extract_chapter_hint, normalize_search_text
from .executor import ExecutionError, apply_plan, rollback_journal, validate_plan
from .items import analyze_audiobook_items
from .journal import JournalError, load_journal
from .models import MediaKind, Plan
from .scanner import scan_library


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="media-janitor",
        description="Inspect, plan, and safely apply reversible media-library cleanup operations.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Create a read-only inventory snapshot")
    scan.add_argument("path", type=Path, help="Library or dataset root")
    scan.add_argument("--include-other", action="store_true", help="Include non-audio/video files")
    scan.add_argument("--json", dest="json_path", type=Path, help="Write the complete snapshot to a JSON file")
    scan.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")

    analyze = subparsers.add_parser(
        "analyze-audiobooks",
        help="Read-only filename analysis for audiobook files",
    )
    analyze.add_argument("path", type=Path, help="Audiobook library or dataset root")
    analyze.add_argument("--json", dest="json_path", type=Path, help="Write all analysis records to JSON")
    analyze.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    analyze.add_argument(
        "--show",
        type=int,
        default=20,
        help="Number of interesting filename analyses to print (default: 20)",
    )

    inspect = subparsers.add_parser(
        "inspect-audiobooks",
        help="Build a read-only item-level report from folders, filenames, and embedded tags",
    )
    inspect.add_argument("path", type=Path, help="Audiobook library or dataset root")
    inspect.add_argument("--json", dest="json_path", type=Path, help="Write the complete item report to JSON")
    inspect.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    inspect.add_argument(
        "--show",
        type=int,
        default=20,
        help="Number of item summaries to print (default: 20)",
    )

    validate = subparsers.add_parser("validate-plan", help="Validate a cleanup plan without writing anything")
    validate.add_argument("plan", type=Path, help="Plan JSON file")

    apply = subparsers.add_parser("apply-plan", help="Apply a fully reversible plan and persist a crash-safe journal")
    apply.add_argument("plan", type=Path, help="Plan JSON file")
    apply.add_argument(
        "--state-dir",
        type=Path,
        default=Path("/state"),
        help="Persistent state directory outside the media root (default: /state)",
    )
    apply.add_argument(
        "--confirm-apply",
        action="store_true",
        help="Required acknowledgement that the reviewed plan should modify the media filesystem",
    )

    rollback = subparsers.add_parser("rollback", help="Reverse all completed operations recorded in a journal")
    rollback.add_argument("journal", type=Path, help="Journal JSON created by apply-plan")
    rollback.add_argument(
        "--confirm-rollback",
        action="store_true",
        help="Required acknowledgement that rollback should modify the media filesystem",
    )

    status = subparsers.add_parser("journal-status", help="Show apply/rollback state from a durable journal")
    status.add_argument("journal", type=Path, help="Journal JSON created by apply-plan")

    return parser


def _load_plan(path: Path) -> Plan:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Plan is not valid JSON: {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"Plan JSON must be an object: {path}")
    return Plan.from_dict(payload)


def run_scan(args: argparse.Namespace) -> int:
    snapshot = scan_library(args.path, include_other=args.include_other)
    counts = Counter(entry.media_kind.value for entry in snapshot.files)

    summary = {
        "schema_version": snapshot.schema_version,
        "created_at": snapshot.created_at,
        "root": snapshot.root,
        "files": len(snapshot.files),
        "directories": len(snapshot.directories),
        "by_kind": dict(sorted(counts.items())),
        "unreadable_paths": len(snapshot.unreadable_paths),
    }
    print(json.dumps(summary, indent=2))

    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        indent = 2 if args.pretty else None
        args.json_path.write_text(json.dumps(snapshot.to_dict(), indent=indent) + "\n", encoding="utf-8")
        print(f"snapshot: {args.json_path}")

    return 0


def run_audiobook_analysis(args: argparse.Namespace) -> int:
    snapshot = scan_library(args.path)
    records: list[dict[str, object]] = []

    for entry in snapshot.files:
        if entry.media_kind is not MediaKind.AUDIOBOOK:
            continue

        name = Path(entry.relative_path).name
        normalized = normalize_search_text(name)
        chapter = extract_chapter_hint(name)
        records.append(
            {
                "path": entry.relative_path,
                "size_bytes": entry.size_bytes,
                "mtime_ns": entry.mtime_ns,
                "normalized_name": normalized.normalized,
                "transformations": list(normalized.transformations),
                "chapter_hint": chapter.to_dict() if chapter else None,
            }
        )

    interesting = [record for record in records if record["transformations"] or record["chapter_hint"]]
    print(
        json.dumps(
            {
                "root": snapshot.root,
                "audiobook_files": len(records),
                "files_with_hints": len(interesting),
                "unreadable_paths": len(snapshot.unreadable_paths),
            },
            indent=2,
        )
    )

    for record in interesting[: max(args.show, 0)]:
        chapter = record["chapter_hint"]
        chapter_text = ""
        if chapter:
            number = chapter["number"]
            chapter_text = f" | {chapter['kind']}" + (f" {number}" if number is not None else "")
        print(f"{record['path']} -> {record['normalized_name']}{chapter_text}")

    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        indent = 2 if args.pretty else None
        payload = {
            "schema_version": snapshot.schema_version,
            "created_at": snapshot.created_at,
            "root": snapshot.root,
            "records": records,
            "unreadable_paths": list(snapshot.unreadable_paths),
        }
        args.json_path.write_text(json.dumps(payload, indent=indent) + "\n", encoding="utf-8")
        print(f"analysis: {args.json_path}")

    return 0


def run_audiobook_inspection(args: argparse.Namespace) -> int:
    snapshot = scan_library(args.path)
    items = analyze_audiobook_items(args.path, snapshot=snapshot)
    audiobook_files = sum(len(item.files) for item in items)
    files_with_metadata = sum(1 for item in items for file in item.files if file.embedded is not None)
    items_with_warnings = sum(1 for item in items if item.warnings)

    print(
        json.dumps(
            {
                "root": snapshot.root,
                "items": len(items),
                "audiobook_files": audiobook_files,
                "files_with_embedded_metadata": files_with_metadata,
                "items_with_warnings": items_with_warnings,
                "unreadable_paths": len(snapshot.unreadable_paths),
            },
            indent=2,
        )
    )

    for item in items[: max(args.show, 0)]:
        author = f" | {item.author_hints[0]}" if item.author_hints else ""
        warning = f" | {len(item.warnings)} warning(s)" if item.warnings else ""
        title = item.title_hint or "unknown title"
        print(f"{item.item_path} -> {title}{author} | confidence {item.confidence:.3f}{warning}")

    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        indent = 2 if args.pretty else None
        payload = {
            "schema_version": 1,
            "created_at": snapshot.created_at,
            "root": snapshot.root,
            "items": [item.to_dict() for item in items],
            "unreadable_paths": list(snapshot.unreadable_paths),
        }
        args.json_path.write_text(json.dumps(payload, indent=indent) + "\n", encoding="utf-8")
        print(f"inspection: {args.json_path}")

    return 0


def run_validate_plan(args: argparse.Namespace) -> int:
    plan = _load_plan(args.plan)
    validate_plan(plan)
    print(
        json.dumps(
            {
                "plan_id": plan.plan_id,
                "root": plan.root,
                "operations": len(plan.operations),
                "reversible": plan.reversible,
                "status": "valid",
            },
            indent=2,
        )
    )
    return 0


def run_apply_plan(args: argparse.Namespace) -> int:
    plan = _load_plan(args.plan)
    state_dir = args.state_dir.expanduser().resolve()
    journal_path = state_dir / "journals" / f"{plan.plan_id}.json"
    journal = apply_plan(plan, journal_path, confirmed=args.confirm_apply)
    print(json.dumps({"status": journal["status"], "journal": str(journal_path)}, indent=2))
    return 0


def run_rollback(args: argparse.Namespace) -> int:
    journal = rollback_journal(args.journal, confirmed=args.confirm_rollback)
    print(json.dumps({"status": journal["status"], "journal": str(args.journal)}, indent=2))
    return 0


def run_journal_status(args: argparse.Namespace) -> int:
    journal = load_journal(args.journal)
    counts = Counter(str(record.get("state")) for record in journal["operations"])
    print(
        json.dumps(
            {
                "status": journal["status"],
                "plan_id": journal["plan"].get("plan_id"),
                "operation_states": dict(sorted(counts.items())),
                "updated_at": journal.get("updated_at"),
            },
            indent=2,
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "scan":
            return run_scan(args)
        if args.command == "analyze-audiobooks":
            return run_audiobook_analysis(args)
        if args.command == "inspect-audiobooks":
            return run_audiobook_inspection(args)
        if args.command == "validate-plan":
            return run_validate_plan(args)
        if args.command == "apply-plan":
            return run_apply_plan(args)
        if args.command == "rollback":
            return run_rollback(args)
        if args.command == "journal-status":
            return run_journal_status(args)
    except (ExecutionError, JournalError, OSError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
