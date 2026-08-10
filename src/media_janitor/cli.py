from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Sequence

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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        return run_scan(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
