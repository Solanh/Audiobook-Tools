from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

from .audiobook import extract_chapter_hint, normalize_search_text
from .metadata import EmbeddedAudioMetadata, MetadataReadResult, read_embedded_audio_metadata
from .models import FileEntry, MediaKind, ScanSnapshot
from .scanner import scan_library

_DISC_DIRECTORY = re.compile(r"^(?:cd|disc|disk|part|pt|volume|vol)[ ._-]*(?:\d+|[ivxlcdm]+)$", re.IGNORECASE)

MetadataReader = Callable[[str | Path], MetadataReadResult]


@dataclass(frozen=True, slots=True)
class AudiobookFileAnalysis:
    path: str
    size_bytes: int
    mtime_ns: int | None
    normalized_name: str
    chapter_hint: dict[str, Any] | None
    embedded: EmbeddedAudioMetadata | None
    metadata_error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "mtime_ns": self.mtime_ns,
            "normalized_name": self.normalized_name,
            "chapter_hint": self.chapter_hint,
            "embedded": self.embedded.to_dict() if self.embedded else None,
            "metadata_error": self.metadata_error,
        }


@dataclass(frozen=True, slots=True)
class AudiobookItemAnalysis:
    item_path: str
    files: tuple[AudiobookFileAnalysis, ...]
    title_hint: str | None
    author_hints: tuple[str, ...]
    narrator_hints: tuple[str, ...]
    series_hint: str | None
    series_index_hint: str | None
    asin: str | None
    isbn: str | None
    total_duration_seconds: float | None
    confidence: float
    evidence: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_path": self.item_path,
            "file_count": len(self.files),
            "title_hint": self.title_hint,
            "author_hints": list(self.author_hints),
            "narrator_hints": list(self.narrator_hints),
            "series_hint": self.series_hint,
            "series_index_hint": self.series_index_hint,
            "identifiers": {"asin": self.asin, "isbn": self.isbn},
            "total_duration_seconds": self.total_duration_seconds,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "warnings": list(self.warnings),
            "files": [file.to_dict() for file in self.files],
        }


def _item_directory(relative_path: str) -> str:
    parent = PurePosixPath(relative_path).parent
    if parent.name and _DISC_DIRECTORY.fullmatch(parent.name):
        parent = parent.parent
    value = parent.as_posix()
    return "." if value in {"", "."} else value


def _clean_values(values: Iterable[str | None]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        cleaned = value.strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return tuple(result)


def _consensus(values: Iterable[str | None]) -> tuple[str | None, float, tuple[str, ...]]:
    cleaned = [value.strip() for value in values if value and value.strip()]
    if not cleaned:
        return None, 0.0, ()

    display_by_key: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for value in cleaned:
        key = value.casefold()
        display_by_key.setdefault(key, value)
        counts[key] += 1

    key, count = counts.most_common(1)[0]
    distinct = tuple(display_by_key[item] for item in sorted(counts, key=lambda item: (-counts[item], item)))
    return display_by_key[key], count / len(cleaned), distinct


def _metadata_for(files: Iterable[AudiobookFileAnalysis]) -> list[EmbeddedAudioMetadata]:
    return [file.embedded for file in files if file.embedded is not None]


def _folder_title(item_path: str, files: tuple[AudiobookFileAnalysis, ...]) -> str | None:
    if item_path != ".":
        return normalize_search_text(PurePosixPath(item_path).name).normalized or None
    if len(files) == 1:
        return normalize_search_text(PurePosixPath(files[0].path).name).normalized or None
    return None


def _build_item(item_path: str, files: tuple[AudiobookFileAnalysis, ...]) -> AudiobookItemAnalysis:
    embedded = _metadata_for(files)
    evidence: list[str] = []
    warnings: list[str] = []

    album, album_ratio, album_values = _consensus(metadata.album for metadata in embedded)
    folder_title = _folder_title(item_path, files)
    title_hint = album or folder_title
    if album:
        evidence.append(f"embedded album agrees on {album!r} for {album_ratio:.0%} of tagged files")
    elif folder_title:
        evidence.append(f"title falls back to folder/filename context: {folder_title!r}")

    if len(album_values) > 1:
        warnings.append(f"conflicting embedded album values: {', '.join(album_values[:4])}")

    primary_author_values: list[str] = []
    for metadata in embedded:
        if metadata.album_artists:
            primary_author_values.extend(metadata.album_artists)
        else:
            primary_author_values.extend(metadata.artists)
    author_primary, author_ratio, author_values = _consensus(primary_author_values)
    author_hints = _clean_values((author_primary, *author_values))
    if author_primary:
        evidence.append(f"embedded author/album-artist consensus: {author_primary!r}")
    if len(author_values) > 1 and author_ratio < 0.75:
        warnings.append(f"conflicting embedded author values: {', '.join(author_values[:4])}")

    narrator_hints = _clean_values(
        narrator
        for metadata in embedded
        for narrator in metadata.narrators
    )
    if narrator_hints:
        evidence.append(f"embedded narrator metadata: {', '.join(narrator_hints[:3])}")

    series_hint, series_ratio, series_values = _consensus(metadata.series for metadata in embedded)
    series_index_hint, _, series_index_values = _consensus(metadata.series_index for metadata in embedded)
    if series_hint:
        evidence.append(f"embedded series consensus: {series_hint!r}")
    if len(series_values) > 1:
        warnings.append(f"conflicting series values: {', '.join(series_values[:4])}")
    if len(series_index_values) > 1:
        warnings.append(f"conflicting series index values: {', '.join(series_index_values[:4])}")

    asin, _, asin_values = _consensus(metadata.asin for metadata in embedded)
    isbn, _, isbn_values = _consensus(metadata.isbn for metadata in embedded)
    if asin:
        evidence.append(f"embedded ASIN: {asin}")
    if isbn:
        evidence.append(f"embedded ISBN: {isbn}")
    if len(asin_values) > 1:
        warnings.append("multiple ASIN values found in one item")
    if len(isbn_values) > 1:
        warnings.append("multiple ISBN values found in one item")

    durations = [metadata.duration_seconds for metadata in embedded if metadata.duration_seconds is not None]
    total_duration = sum(durations) if durations else None

    metadata_errors = sum(1 for file in files if file.metadata_error)
    if metadata_errors:
        warnings.append(f"embedded metadata unreadable for {metadata_errors}/{len(files)} files")

    if item_path == "." and len(files) > 1:
        warnings.append("multiple audiobook files live directly at the scan root; item boundary is uncertain")

    confidence = 0.15 if title_hint else 0.0
    if album:
        confidence += 0.30 * album_ratio
    if author_primary:
        confidence += 0.20 * max(author_ratio, 0.5)
    if asin or isbn:
        confidence += 0.20
    if series_hint:
        confidence += 0.10 * max(series_ratio, 0.5)
    if embedded and metadata_errors == 0:
        confidence += 0.05
    if len(album_values) > 1:
        confidence -= 0.15
    if len(author_values) > 1 and author_ratio < 0.75:
        confidence -= 0.10
    confidence = round(min(max(confidence, 0.0), 0.99), 3)

    return AudiobookItemAnalysis(
        item_path=item_path,
        files=files,
        title_hint=title_hint,
        author_hints=author_hints,
        narrator_hints=narrator_hints,
        series_hint=series_hint,
        series_index_hint=series_index_hint,
        asin=asin,
        isbn=isbn,
        total_duration_seconds=round(total_duration, 3) if total_duration is not None else None,
        confidence=confidence,
        evidence=tuple(evidence),
        warnings=tuple(warnings),
    )


def analyze_audiobook_items(
    root: str | Path,
    *,
    snapshot: ScanSnapshot | None = None,
    metadata_reader: MetadataReader = read_embedded_audio_metadata,
) -> tuple[AudiobookItemAnalysis, ...]:
    snapshot = snapshot or scan_library(root)
    root_path = Path(snapshot.root)
    grouped: dict[str, list[FileEntry]] = defaultdict(list)

    for entry in snapshot.files:
        if entry.media_kind is MediaKind.AUDIOBOOK:
            grouped[_item_directory(entry.relative_path)].append(entry)

    items: list[AudiobookItemAnalysis] = []
    for item_path, entries in sorted(grouped.items(), key=lambda pair: pair[0].casefold()):
        files: list[AudiobookFileAnalysis] = []
        for entry in sorted(entries, key=lambda value: value.relative_path.casefold()):
            filename = PurePosixPath(entry.relative_path).name
            normalization = normalize_search_text(filename)
            chapter = extract_chapter_hint(filename)
            result = metadata_reader(root_path / Path(entry.relative_path))
            files.append(
                AudiobookFileAnalysis(
                    path=entry.relative_path,
                    size_bytes=entry.size_bytes,
                    mtime_ns=entry.mtime_ns,
                    normalized_name=normalization.normalized,
                    chapter_hint=chapter.to_dict() if chapter else None,
                    embedded=result.metadata,
                    metadata_error=result.error,
                )
            )
        items.append(_build_item(item_path, tuple(files)))

    return tuple(items)
