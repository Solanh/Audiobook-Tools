from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Sequence

from .audiobook import extract_chapter_hint, normalize_search_text
from .models import MediaKind
from .scanner import scan_library


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="media-janitor",
        description="Inspect a messy media library without modifying it.",
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

    return parser


def run_scan(args: argparse.Namespace) -> int:
    snapshot = scan_library(args.path, include_other=args.include_other)
    counts = Counter(entry.media_kind.value for entry in snapshot.files)

    summary = {
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
            "root": snapshot.root,
            "records": records,
            "unreadable_paths": list(snapshot.unreadable_paths),
        }
        args.json_path.write_text(json.dumps(payload, indent=indent) + "\n", encoding="utf-8")
        print(f"analysis: {args.json_path}")

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        return run_scan(args)
    if args.command == "analyze-audiobooks":
        return run_audiobook_analysis(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
