from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from tinytag import TinyTag, TinyTagException


@dataclass(frozen=True, slots=True)
class EmbeddedAudioMetadata:
    title: str | None = None
    album: str | None = None
    artists: tuple[str, ...] = ()
    album_artists: tuple[str, ...] = ()
    narrators: tuple[str, ...] = ()
    series: str | None = None
    series_index: str | None = None
    asin: str | None = None
    isbn: str | None = None
    track: int | None = None
    track_total: int | None = None
    disc: int | None = None
    disc_total: int | None = None
    year: str | None = None
    genre: str | None = None
    duration_seconds: float | None = None
    bitrate_kbps: float | None = None
    sample_rate_hz: int | None = None
    channels: int | None = None
    other: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "album": self.album,
            "artists": list(self.artists),
            "album_artists": list(self.album_artists),
            "narrators": list(self.narrators),
            "series": self.series,
            "series_index": self.series_index,
            "asin": self.asin,
            "isbn": self.isbn,
            "track": self.track,
            "track_total": self.track_total,
            "disc": self.disc,
            "disc_total": self.disc_total,
            "year": self.year,
            "genre": self.genre,
            "duration_seconds": self.duration_seconds,
            "bitrate_kbps": self.bitrate_kbps,
            "sample_rate_hz": self.sample_rate_hz,
            "channels": self.channels,
            "other": {key: list(values) for key, values in sorted(self.other.items())},
        }


@dataclass(frozen=True, slots=True)
class MetadataReadResult:
    metadata: EmbeddedAudioMetadata | None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": self.metadata.to_dict() if self.metadata else None,
            "error": self.error,
        }


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dedupe(values: Iterable[object]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean(value)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return tuple(result)


def _normalize_other(other: object) -> dict[str, tuple[str, ...]]:
    if not isinstance(other, dict):
        return {}
    normalized: dict[str, tuple[str, ...]] = {}
    for key, raw_values in other.items():
        if isinstance(raw_values, (list, tuple, set)):
            values = _dedupe(raw_values)
        else:
            values = _dedupe((raw_values,))
        if values:
            normalized[str(key)] = values
    return normalized


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _first_other(other: dict[str, tuple[str, ...]], *aliases: str) -> str | None:
    wanted = {_normalized_key(alias) for alias in aliases}
    for key, values in other.items():
        if _normalized_key(key) in wanted and values:
            return values[0]
    return None


def _all_other(other: dict[str, tuple[str, ...]], *aliases: str) -> tuple[str, ...]:
    wanted = {_normalized_key(alias) for alias in aliases}
    values: list[str] = []
    for key, raw_values in other.items():
        if _normalized_key(key) in wanted:
            values.extend(raw_values)
    return _dedupe(values)


def metadata_from_tinytag(tag: object) -> EmbeddedAudioMetadata:
    other = _normalize_other(getattr(tag, "other", {}))

    artists = _dedupe(
        (
            getattr(tag, "artist", None),
            *_all_other(other, "artist", "author", "authors", "writer"),
        )
    )
    album_artists = _dedupe(
        (
            getattr(tag, "albumartist", None),
            *_all_other(other, "albumartist", "album artist"),
        )
    )
    narrators = _all_other(other, "narrator", "narrators", "reader", "read by", "readby")

    return EmbeddedAudioMetadata(
        title=_clean(getattr(tag, "title", None)),
        album=_clean(getattr(tag, "album", None)),
        artists=artists,
        album_artists=album_artists,
        narrators=narrators,
        series=_first_other(other, "series", "series name", "seriesname"),
        series_index=_first_other(
            other,
            "series index",
            "seriesindex",
            "series part",
            "seriespart",
            "series number",
            "seriesnumber",
        ),
        asin=_first_other(other, "asin", "audible asin", "audibleasin"),
        isbn=_first_other(other, "isbn", "isbn10", "isbn13"),
        track=getattr(tag, "track", None),
        track_total=getattr(tag, "track_total", None),
        disc=getattr(tag, "disc", None),
        disc_total=getattr(tag, "disc_total", None),
        year=_clean(getattr(tag, "year", None)),
        genre=_clean(getattr(tag, "genre", None)),
        duration_seconds=getattr(tag, "duration", None),
        bitrate_kbps=getattr(tag, "bitrate", None),
        sample_rate_hz=getattr(tag, "samplerate", None),
        channels=getattr(tag, "channels", None),
        other=other,
    )


def read_embedded_audio_metadata(path: str | Path) -> MetadataReadResult:
    source = Path(path)
    try:
        tag = TinyTag.get(str(source), image=False)
    except (TinyTagException, OSError, ValueError) as error:
        return MetadataReadResult(metadata=None, error=f"{type(error).__name__}: {error}")
    return MetadataReadResult(metadata=metadata_from_tinytag(tag))
