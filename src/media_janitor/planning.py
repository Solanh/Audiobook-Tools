from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .models import FileOperation, OperationKind, Plan
from .scanner import AUDIO_EXTENSIONS
from .state import ProposalRecord, StateError, StateStore


class DraftPlanError(RuntimeError):
    pass


_LAYOUTS = {"author-title", "author-series-title", "series-title"}
_UNSAFE_COMPONENT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class DraftPlanResult:
    proposal_id: str
    source_report_id: str
    candidate_sha256: str
    layout: str
    source_item_path: str
    target_item_path: str
    plan: Plan
    companion_files: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "source_report_id": self.source_report_id,
            "candidate_sha256": self.candidate_sha256,
            "layout": self.layout,
            "source_item_path": self.source_item_path,
            "target_item_path": self.target_item_path,
            "companion_files": list(self.companion_files),
            "warnings": list(self.warnings),
            "plan": self.plan.to_dict(),
        }


def _component(value: object, *, label: str) -> str:
    text = str(value or "").strip()
    text = _UNSAFE_COMPONENT.sub(" - ", text)
    text = _WHITESPACE.sub(" ", text).strip(" .-")
    if not text or text in {".", ".."}:
        raise DraftPlanError(f"Provider candidate is missing a usable {label}")
    if len(text) > 180:
        text = text[:180].rstrip(" .-")
    if not text:
        raise DraftPlanError(f"Provider candidate produced an empty {label}")
    return text


def _sequence_prefix(sequence: object) -> str | None:
    text = str(sequence or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d+", text):
        return text.zfill(2)
    if re.fullmatch(r"\d+(?:\.\d+)+", text):
        return text
    cleaned = _component(text, label="series sequence")
    return cleaned


def _first_series(provider_result: dict[str, Any]) -> tuple[str | None, str | None]:
    values = provider_result.get("series")
    if not isinstance(values, list):
        return None, None
    for value in values:
        if not isinstance(value, dict):
            continue
        name = value.get("name")
        if name:
            return str(name), str(value.get("sequence") or "").strip() or None
    return None, None


def canonical_item_path(provider_result: dict[str, Any], *, layout: str) -> str:
    if layout not in _LAYOUTS:
        raise ValueError(f"Unknown layout {layout!r}; choices: {', '.join(sorted(_LAYOUTS))}")

    title = _component(provider_result.get("title"), label="title")
    raw_authors = provider_result.get("authors")
    authors = [str(value).strip() for value in raw_authors] if isinstance(raw_authors, list) else []
    authors = [value for value in authors if value]
    author = _component(" & ".join(authors), label="author") if authors else None

    series_name, raw_sequence = _first_series(provider_result)
    series = _component(series_name, label="series") if series_name else None
    sequence = _sequence_prefix(raw_sequence)
    book_name = f"{sequence} - {title}" if series and sequence else title

    if layout == "author-title":
        if not author:
            raise DraftPlanError("author-title layout requires provider author metadata")
        parts = (author, title)
    elif layout == "author-series-title":
        if not author:
            raise DraftPlanError("author-series-title layout requires provider author metadata")
        parts = (author, series, book_name) if series else (author, title)
    else:
        if series:
            parts = (series, book_name)
        elif author:
            parts = (author, title)
        else:
            parts = (title,)

    return PurePosixPath(*(part for part in parts if part)).as_posix()


def _selected_candidate(proposal: ProposalRecord) -> dict[str, Any]:
    candidate = proposal.candidate
    provider_match = candidate.get("provider_match")
    selected = candidate.get("selected_candidate")
    if not isinstance(provider_match, dict) or not isinstance(selected, dict):
        raise DraftPlanError("Proposal does not contain a provider match and selected candidate")
    if provider_match.get("status") != "strong_identity_candidate":
        raise DraftPlanError("Draft planning currently requires a strong provider identity candidate")
    provider_result = selected.get("provider_result")
    if not isinstance(provider_result, dict):
        raise DraftPlanError("Proposal selected candidate is missing provider_result")
    return selected


def _local_item(proposal: ProposalRecord) -> dict[str, Any]:
    current = proposal.candidate.get("current_server_match")
    if not isinstance(current, dict):
        raise DraftPlanError("Proposal is missing current-server match context")
    local = current.get("local_item")
    if not isinstance(local, dict):
        raise DraftPlanError("Proposal is missing local item context")
    return local


def _relative_parts(path: str) -> tuple[str, ...]:
    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts:
        raise DraftPlanError(f"Unsafe relative media path in proposal: {path!r}")
    return tuple(part for part in value.parts if part not in {"", "."})


def _suffix_under_item(source: str, item_path: str) -> PurePosixPath:
    source_parts = _relative_parts(source)
    item_parts = _relative_parts(item_path) if item_path != "." else ()
    if item_parts:
        if source_parts[: len(item_parts)] != item_parts:
            raise DraftPlanError(f"Proposed file {source!r} is not under item path {item_path!r}")
        suffix = source_parts[len(item_parts) :]
    else:
        suffix = source_parts
    if not suffix:
        raise DraftPlanError(f"Could not derive a relative file path for {source!r}")
    return PurePosixPath(*suffix)


def _proposal_audio_files(local_item: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_files = local_item.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise DraftPlanError("Approved proposal does not contain source file fingerprints")
    result: dict[str, dict[str, Any]] = {}
    for value in raw_files:
        if not isinstance(value, dict):
            raise DraftPlanError("Approved proposal contains an invalid source file record")
        path = value.get("path")
        size = value.get("size_bytes")
        mtime = value.get("mtime_ns")
        if not isinstance(path, str) or not isinstance(size, int) or not isinstance(mtime, int):
            raise DraftPlanError("Approved proposal source file is missing path/size/mtime fingerprints")
        result[path] = value
    return result


def _live_files(root: Path, item_path: str) -> tuple[Path, ...]:
    if item_path == ".":
        # Root-level items are deliberately restricted to the approved audio files.
        # Recursing the entire media root would absorb unrelated books.
        return ()
    item_root = root.joinpath(*_relative_parts(item_path))
    if not item_root.exists() or not item_root.is_dir():
        raise DraftPlanError(f"Approved item directory no longer exists: {item_root}")
    result: list[Path] = []
    for path in item_root.rglob("*"):
        if path.is_symlink():
            raise DraftPlanError(f"Symlink found inside approved item tree: {path}")
        if path.is_file():
            result.append(path)
    result.sort(key=lambda value: value.as_posix().casefold())
    return tuple(result)


def _mkdir_operations(root: Path, relative_directories: Iterable[PurePosixPath], evidence: tuple[str, ...]) -> list[FileOperation]:
    requested: set[PurePosixPath] = set()
    for directory in relative_directories:
        current = PurePosixPath()
        for part in directory.parts:
            current /= part
            if current.parts:
                requested.add(current)

    operations: list[FileOperation] = []
    for directory in sorted(requested, key=lambda value: (len(value.parts), value.as_posix().casefold())):
        host_path = root.joinpath(*directory.parts)
        if host_path.exists():
            if not host_path.is_dir() or host_path.is_symlink():
                raise DraftPlanError(f"Destination directory path is not a normal directory: {host_path}")
            continue
        operations.append(
            FileOperation(
                kind=OperationKind.MKDIR,
                destination=directory.as_posix(),
                reason="create canonical audiobook destination directory",
                confidence=1.0,
                evidence=evidence,
            )
        )
    return operations


def build_draft_plan(
    store: StateStore,
    proposal_id: str,
    *,
    layout: str = "author-series-title",
) -> DraftPlanResult:
    proposal = store.get_proposal(proposal_id)
    if proposal.status != "approved":
        raise DraftPlanError(
            f"Proposal {proposal_id} is {proposal.status}; only explicitly approved proposals can produce draft plans"
        )

    report = store.get_report(proposal.source_report_id)
    if not report.root:
        raise DraftPlanError("Source identification report is missing the media root")
    root = Path(report.root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise DraftPlanError(f"Media root is unavailable: {root}")

    selected = _selected_candidate(proposal)
    provider_result = selected["provider_result"]
    target_item = canonical_item_path(provider_result, layout=layout)
    local_item = _local_item(proposal)
    source_item = str(local_item.get("item_path") or "").strip() or "."
    approved_audio = _proposal_audio_files(local_item)

    evidence = (
        f"approved proposal: {proposal.proposal_id}",
        f"candidate sha256: {proposal.candidate_sha256}",
        f"provider identity score: {selected.get('identity_score')}",
        f"provider edition score: {selected.get('edition_score')}",
        f"layout: {layout}",
    )

    live = _live_files(root, source_item)
    approved_paths = set(approved_audio)
    companions: list[str] = []
    live_relative: dict[str, Path] = {}
    for path in live:
        relative = path.relative_to(root).as_posix()
        live_relative[relative] = path
        if path.suffix.lower() in AUDIO_EXTENSIONS and relative not in approved_paths:
            raise DraftPlanError(
                f"Unapproved audio file found inside item tree: {relative}. "
                "Re-run inspection/review before planning; this may be a multi-book or split-layout folder."
            )
        if relative not in approved_paths:
            companions.append(relative)

    source_records: list[tuple[str, int, int, bool]] = []
    for relative, record in approved_audio.items():
        source = root.joinpath(*_relative_parts(relative))
        if source.is_symlink() or not source.is_file():
            raise DraftPlanError(f"Approved source file is missing or no longer a normal file: {relative}")
        stat = source.stat()
        if stat.st_size != record["size_bytes"] or stat.st_mtime_ns != record["mtime_ns"]:
            raise DraftPlanError(f"Approved source fingerprint is stale: {relative}")
        source_records.append((relative, stat.st_size, stat.st_mtime_ns, False))

    for relative in companions:
        source = live_relative[relative]
        stat = source.stat()
        source_records.append((relative, stat.st_size, stat.st_mtime_ns, True))

    if source_item == "." and companions:
        raise DraftPlanError("Root-level audiobook items cannot safely infer companion-file ownership")

    destinations: dict[str, str] = {}
    move_records: list[tuple[str, str, int, int, bool]] = []
    target_path = PurePosixPath(target_item)
    for relative, size, mtime, companion in source_records:
        suffix = _suffix_under_item(relative, source_item)
        destination = (target_path / suffix).as_posix()
        if destination in destinations and destinations[destination] != relative:
            raise DraftPlanError(
                f"Two source files would collide at {destination!r}: {destinations[destination]!r} and {relative!r}"
            )
        destinations[destination] = relative
        if destination == relative:
            continue
        destination_host = root.joinpath(*_relative_parts(destination))
        if destination_host.exists():
            raise DraftPlanError(f"Draft destination already exists: {destination}")
        move_records.append((relative, destination, size, mtime, companion))

    if not move_records:
        raise DraftPlanError(f"Approved item is already at canonical target path {target_item!r}; no draft moves are needed")

    destination_directories = {PurePosixPath(destination).parent for _, destination, *_ in move_records}
    operations = _mkdir_operations(root, destination_directories, evidence)
    for source, destination, size, mtime, companion in sorted(move_records, key=lambda value: value[0].casefold()):
        operations.append(
            FileOperation(
                kind=OperationKind.MOVE,
                source=source,
                destination=destination,
                reason=(
                    "move companion file with approved audiobook"
                    if companion
                    else "move approved audiobook file into canonical folder"
                ),
                confidence=1.0 if companion else float(selected.get("identity_score") or 0.0),
                evidence=evidence,
                expected_source_size_bytes=size,
                expected_source_mtime_ns=mtime,
            )
        )

    warnings = (
        "Draft plan preserves existing filenames; it does not rewrite track names or embedded metadata.",
        "Old source directories are intentionally not removed because generic directory removal is not reversible yet.",
    )
    if companions:
        warnings += (f"The plan carries {len(companions)} non-audio companion file(s) with the approved item.",)

    return DraftPlanResult(
        proposal_id=proposal.proposal_id,
        source_report_id=proposal.source_report_id,
        candidate_sha256=proposal.candidate_sha256,
        layout=layout,
        source_item_path=source_item,
        target_item_path=target_item,
        plan=Plan(root=str(root), operations=tuple(operations)),
        companion_files=tuple(companions),
        warnings=warnings,
    )
