from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Sequence

from .audiobook import extract_chapter_hint, normalize_search_text
from .audiobookshelf import AudiobookshelfError, client_from_environment
from .executor import ExecutionError, apply_plan, rollback_journal, validate_plan
from .items import analyze_audiobook_items
from .journal import JournalError, load_journal
from .matching import match_audiobook_items
from .models import MediaKind, Plan
from .provider_matching import rank_provider_results
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

    abs_inventory = subparsers.add_parser(
        "audiobookshelf-inventory",
        help="Read Audiobookshelf library metadata without modifying the server",
    )
    abs_inventory.add_argument(
        "--library-id",
        help="Audiobookshelf library id; auto-selects when exactly one book library is available",
    )
    abs_inventory.add_argument("--json", dest="json_path", type=Path, help="Write normalized library items to JSON")
    abs_inventory.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    abs_inventory.add_argument(
        "--show",
        type=int,
        default=20,
        help="Number of Audiobookshelf item summaries to print (default: 20)",
    )

    abs_match = subparsers.add_parser(
        "match-audiobookshelf",
        help="Compare local audiobook inspection data to existing Audiobookshelf items without writing anything",
    )
    abs_match.add_argument("path", type=Path, help="Audiobook library or dataset root")
    abs_match.add_argument(
        "--library-id",
        help="Audiobookshelf library id; auto-selects when exactly one book library is available",
    )
    abs_match.add_argument("--json", dest="json_path", type=Path, help="Write the complete match report to JSON")
    abs_match.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    abs_match.add_argument(
        "--show",
        type=int,
        default=20,
        help="Number of local match summaries to print (default: 20)",
    )
    abs_match.add_argument(
        "--candidate-limit",
        type=int,
        default=3,
        help="Number of ranked Audiobookshelf candidates to retain per local item (default: 3)",
    )

    identify = subparsers.add_parser(
        "identify-audiobooks",
        help="Search an Audiobookshelf metadata provider for local items not already strongly matched on the server",
    )
    identify.add_argument("path", type=Path, help="Audiobook library or dataset root")
    identify.add_argument(
        "--library-id",
        help="Audiobookshelf library id; auto-selects when exactly one book library is available",
    )
    identify.add_argument(
        "--provider",
        default="audible",
        help="Audiobookshelf metadata-provider slug to search (default: audible)",
    )
    identify.add_argument(
        "--max-provider-searches",
        type=int,
        default=10,
        help="Maximum unresolved local items to query against the provider in one run (default: 10)",
    )
    identify.add_argument(
        "--candidate-limit",
        type=int,
        default=3,
        help="Number of provider candidates to retain per searched local item (default: 3)",
    )
    identify.add_argument("--json", dest="json_path", type=Path, help="Write the complete identification report to JSON")
    identify.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    identify.add_argument(
        "--show",
        type=int,
        default=20,
        help="Number of unresolved-item summaries to print (default: 20)",
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


def _select_audiobookshelf_library(libraries: Sequence[object], library_id: str | None):
    if library_id:
        selected = next((library for library in libraries if getattr(library, "id", None) == library_id), None)
        if selected is None:
            known = ", ".join(str(getattr(library, "id", "unknown")) for library in libraries) or "none"
            raise ValueError(f"Audiobookshelf library id {library_id!r} was not found; available: {known}")
        return selected

    book_libraries = [library for library in libraries if getattr(library, "media_type", None) == "book"]
    if len(book_libraries) == 1:
        return book_libraries[0]
    if len(libraries) == 1:
        return libraries[0]

    choices = ", ".join(
        f"{getattr(library, 'id', 'unknown')} ({getattr(library, 'name', 'unnamed')})"
        for library in book_libraries or libraries
    )
    raise ValueError(f"Multiple Audiobookshelf libraries are available; pass --library-id. Choices: {choices}")


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


def run_audiobookshelf_inventory(args: argparse.Namespace) -> int:
    client = client_from_environment()
    libraries = client.libraries()
    selected = _select_audiobookshelf_library(libraries, args.library_id)
    items = client.library_items(selected.id)
    print(
        json.dumps(
            {
                "server": client.base_url,
                "library": selected.to_dict(),
                "items": len(items),
            },
            indent=2,
        )
    )

    for item in items[: max(args.show, 0)]:
        author = f" | {item.authors[0]}" if item.authors else ""
        title = item.title or "unknown title"
        path = f" | {item.path}" if item.path else ""
        print(f"{item.id} -> {title}{author}{path}")

    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        indent = 2 if args.pretty else None
        payload = {
            "schema_version": 1,
            "server": client.base_url,
            "library": selected.to_dict(),
            "items": [item.to_dict() for item in items],
        }
        args.json_path.write_text(json.dumps(payload, indent=indent) + "\n", encoding="utf-8")
        print(f"audiobookshelf inventory: {args.json_path}")

    return 0


def run_audiobookshelf_match(args: argparse.Namespace) -> int:
    if args.candidate_limit < 1:
        raise ValueError("--candidate-limit must be at least 1")

    snapshot = scan_library(args.path)
    local_items = analyze_audiobook_items(args.path, snapshot=snapshot)

    client = client_from_environment()
    libraries = client.libraries()
    selected = _select_audiobookshelf_library(libraries, args.library_id)
    server_items = client.library_items(selected.id)

    matches = match_audiobook_items(
        local_items,
        server_items,
        candidate_limit=args.candidate_limit,
    )
    status_counts = Counter(match.status for match in matches)

    print(
        json.dumps(
            {
                "root": snapshot.root,
                "server": client.base_url,
                "library": selected.to_dict(),
                "local_items": len(local_items),
                "audiobookshelf_items": len(server_items),
                "status_counts": dict(sorted(status_counts.items())),
            },
            indent=2,
        )
    )

    for match in matches[: max(args.show, 0)]:
        title = match.local_item.title_hint or match.local_item.item_path
        if match.best:
            best_title = match.best.item.title or match.best.item.id
            print(f"{match.status}: {title} -> {best_title} [{match.best.score:.3f}]")
        else:
            print(f"{match.status}: {title} -> no Audiobookshelf candidate")

    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        indent = 2 if args.pretty else None
        payload = {
            "schema_version": 1,
            "created_at": snapshot.created_at,
            "root": snapshot.root,
            "server": client.base_url,
            "library": selected.to_dict(),
            "local_items": len(local_items),
            "audiobookshelf_items": len(server_items),
            "status_counts": dict(sorted(status_counts.items())),
            "matches": [match.to_dict() for match in matches],
            "unreadable_paths": list(snapshot.unreadable_paths),
        }
        args.json_path.write_text(json.dumps(payload, indent=indent) + "\n", encoding="utf-8")
        print(f"audiobookshelf matches: {args.json_path}")

    return 0


def run_identify_audiobooks(args: argparse.Namespace) -> int:
    if args.candidate_limit < 1:
        raise ValueError("--candidate-limit must be at least 1")
    if args.max_provider_searches < 1:
        raise ValueError("--max-provider-searches must be at least 1")

    snapshot = scan_library(args.path)
    local_items = analyze_audiobook_items(args.path, snapshot=snapshot)

    client = client_from_environment()
    libraries = client.libraries()
    selected = _select_audiobookshelf_library(libraries, args.library_id)
    server_items = client.library_items(selected.id)
    server_matches = match_audiobook_items(local_items, server_items, candidate_limit=3)

    providers = client.metadata_providers()
    provider = next((value for value in providers if value.value == args.provider), None)
    if provider is None:
        choices = ", ".join(f"{value.value} ({value.text})" for value in providers) or "none"
        raise ValueError(f"Audiobookshelf metadata provider {args.provider!r} is unavailable; choices: {choices}")

    unresolved = [match for match in server_matches if match.status != "strong_candidate"]
    records: list[dict[str, object]] = []
    provider_searches = 0
    provider_status_counts: Counter[str] = Counter()

    for server_match in unresolved:
        local = server_match.local_item
        record: dict[str, object] = {
            "local_item_path": local.item_path,
            "current_server_match": server_match.to_dict(),
            "provider_search": None,
            "provider_search_skipped_reason": None,
        }

        title = (local.title_hint or "").strip()
        if not title:
            record["provider_search_skipped_reason"] = "no usable local title hint"
        elif provider_searches >= args.max_provider_searches:
            record["provider_search_skipped_reason"] = "provider-search cap reached"
        else:
            author = local.author_hints[0] if local.author_hints else None
            raw_results = client.search_books(provider.value, title, author)
            provider_match = rank_provider_results(
                local,
                provider.value,
                raw_results,
                candidate_limit=args.candidate_limit,
            )
            record["provider_search"] = provider_match.to_dict()
            provider_searches += 1
            provider_status_counts[provider_match.status] += 1

        records.append(record)

    skipped = sum(1 for record in records if record["provider_search_skipped_reason"])
    summary = {
        "root": snapshot.root,
        "server": client.base_url,
        "library": selected.to_dict(),
        "provider": provider.to_dict(),
        "local_items": len(local_items),
        "strong_current_server_matches": len(local_items) - len(unresolved),
        "unresolved_items": len(unresolved),
        "provider_searches": provider_searches,
        "provider_searches_skipped": skipped,
        "provider_status_counts": dict(sorted(provider_status_counts.items())),
    }
    print(json.dumps(summary, indent=2))

    for record in records[: max(args.show, 0)]:
        server_match = record["current_server_match"]
        local = server_match["local_item"]
        title = local.get("title_hint") or record["local_item_path"]
        provider_search = record["provider_search"]
        if provider_search and provider_search.get("candidates"):
            best = provider_search["candidates"][0]
            provider_title = best["provider_result"].get("title") or "unknown title"
            identity_score = best["identity_score"]
            edition_score = best["edition_score"]
            edition_text = f", edition {edition_score:.3f}" if edition_score is not None else ", edition unknown"
            print(
                f"{provider_search['status']}: {title} -> {provider_title} "
                f"[identity {identity_score:.3f}{edition_text}]"
            )
        elif record["provider_search_skipped_reason"]:
            print(f"skipped: {title} | {record['provider_search_skipped_reason']}")
        else:
            print(f"no_candidate: {title} -> no {provider.value} result")

    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        indent = 2 if args.pretty else None
        payload = {
            "schema_version": 1,
            "created_at": snapshot.created_at,
            **summary,
            "records": records,
            "unreadable_paths": list(snapshot.unreadable_paths),
        }
        args.json_path.write_text(json.dumps(payload, indent=indent) + "\n", encoding="utf-8")
        print(f"identification report: {args.json_path}")

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
        if args.command == "audiobookshelf-inventory":
            return run_audiobookshelf_inventory(args)
        if args.command == "match-audiobookshelf":
            return run_audiobookshelf_match(args)
        if args.command == "identify-audiobooks":
            return run_identify_audiobooks(args)
        if args.command == "validate-plan":
            return run_validate_plan(args)
        if args.command == "apply-plan":
            return run_apply_plan(args)
        if args.command == "rollback":
            return run_rollback(args)
        if args.command == "journal-status":
            return run_journal_status(args)
    except (AudiobookshelfError, ExecutionError, JournalError, OSError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
