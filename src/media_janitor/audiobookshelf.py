from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen


class AudiobookshelfError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AudiobookshelfLibrary:
    id: str
    name: str
    media_type: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "media_type": self.media_type}


@dataclass(frozen=True, slots=True)
class AudiobookshelfItem:
    id: str
    library_id: str | None
    path: str | None
    title: str | None
    authors: tuple[str, ...]
    narrators: tuple[str, ...]
    series: tuple[tuple[str, str | None], ...]
    duration_seconds: float | None
    asin: str | None
    isbn: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "library_id": self.library_id,
            "path": self.path,
            "title": self.title,
            "authors": list(self.authors),
            "narrators": list(self.narrators),
            "series": [{"name": name, "sequence": sequence} for name, sequence in self.series],
            "duration_seconds": self.duration_seconds,
            "asin": self.asin,
            "isbn": self.isbn,
        }


@dataclass(frozen=True, slots=True)
class AudiobookshelfMetadataProvider:
    value: str
    text: str

    def to_dict(self) -> dict[str, str]:
        return {"value": self.value, "text": self.text}


@dataclass(frozen=True, slots=True)
class ProviderBookResult:
    provider: str
    provider_id: str | None
    title: str | None
    subtitle: str | None
    authors: tuple[str, ...]
    narrators: tuple[str, ...]
    series: tuple[tuple[str, str | None], ...]
    duration_seconds: float | None
    asin: str | None
    isbn: str | None
    language: str | None
    publisher: str | None
    published_year: str | None
    abridged: bool | None
    cover: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "provider_id": self.provider_id,
            "title": self.title,
            "subtitle": self.subtitle,
            "authors": list(self.authors),
            "narrators": list(self.narrators),
            "series": [{"name": name, "sequence": sequence} for name, sequence in self.series],
            "duration_seconds": self.duration_seconds,
            "asin": self.asin,
            "isbn": self.isbn,
            "language": self.language,
            "publisher": self.publisher,
            "published_year": self.published_year,
            "abridged": self.abridged,
            "cover": self.cover,
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


def _name_values(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        names: list[object] = []
        for item in value:
            if isinstance(item, dict):
                names.append(item.get("name") or item.get("author") or item.get("narrator"))
            else:
                names.append(item)
        return _dedupe(names)
    if isinstance(value, str):
        return _dedupe(part.strip() for part in value.split(","))
    return ()


def _series_values(value: object) -> tuple[tuple[str, str | None], ...]:
    if not isinstance(value, list):
        return ()
    result: list[tuple[str, str | None]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if isinstance(item, dict):
            name = _clean(item.get("name") or item.get("series"))
            sequence = _clean(item.get("sequence") or item.get("position"))
        else:
            name = _clean(item)
            sequence = None
        if not name:
            continue
        key = (name.casefold(), (sequence or "").casefold())
        if key in seen:
            continue
        seen.add(key)
        result.append((name, sequence))
    return tuple(result)


def normalize_library(value: dict[str, Any]) -> AudiobookshelfLibrary:
    library_id = _clean(value.get("id"))
    if not library_id:
        raise AudiobookshelfError("Audiobookshelf library response is missing id")
    return AudiobookshelfLibrary(
        id=library_id,
        name=_clean(value.get("name")) or library_id,
        media_type=_clean(value.get("mediaType")),
    )


def normalize_item(value: dict[str, Any]) -> AudiobookshelfItem:
    item_id = _clean(value.get("id"))
    if not item_id:
        raise AudiobookshelfError("Audiobookshelf item response is missing id")

    media = value.get("media") if isinstance(value.get("media"), dict) else {}
    metadata = media.get("metadata") if isinstance(media.get("metadata"), dict) else {}

    authors = _name_values(metadata.get("authors"))
    if not authors:
        authors = _name_values(metadata.get("authorName"))

    narrators = _name_values(metadata.get("narrators"))
    if not narrators:
        narrators = _name_values(metadata.get("narratorName"))

    duration = media.get("duration")
    duration_seconds = float(duration) if isinstance(duration, (int, float)) else None

    return AudiobookshelfItem(
        id=item_id,
        library_id=_clean(value.get("libraryId")),
        path=_clean(value.get("path")),
        title=_clean(metadata.get("title")),
        authors=authors,
        narrators=narrators,
        series=_series_values(metadata.get("series")),
        duration_seconds=duration_seconds,
        asin=_clean(metadata.get("asin")),
        isbn=_clean(metadata.get("isbn")),
    )


def normalize_metadata_provider(value: dict[str, Any]) -> AudiobookshelfMetadataProvider:
    provider_value = _clean(value.get("value"))
    if not provider_value:
        raise AudiobookshelfError("Audiobookshelf metadata-provider response is missing value")
    return AudiobookshelfMetadataProvider(
        value=provider_value,
        text=_clean(value.get("text")) or provider_value,
    )


def normalize_provider_book(provider: str, value: dict[str, Any]) -> ProviderBookResult:
    clean_provider = provider.strip()
    if not clean_provider:
        raise ValueError("provider is required")

    duration_seconds: float | None = None
    duration = value.get("duration")
    if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration > 0:
        # Audiobookshelf provider results expose audiobook duration in minutes.
        duration_seconds = float(duration) * 60.0

    authors = _name_values(value.get("authors"))
    if not authors:
        authors = _name_values(value.get("author"))

    narrators = _name_values(value.get("narrators"))
    if not narrators:
        narrators = _name_values(value.get("narrator"))

    provider_id = _clean(value.get("id"))
    if not provider_id:
        provider_id = _clean(value.get("asin")) or _clean(value.get("key")) or _clean(value.get("edition"))

    abridged_raw = value.get("abridged")
    abridged = abridged_raw if isinstance(abridged_raw, bool) else None

    return ProviderBookResult(
        provider=clean_provider,
        provider_id=provider_id,
        title=_clean(value.get("title")),
        subtitle=_clean(value.get("subtitle")),
        authors=authors,
        narrators=narrators,
        series=_series_values(value.get("series")),
        duration_seconds=duration_seconds,
        asin=_clean(value.get("asin")),
        isbn=_clean(value.get("isbn")),
        language=_clean(value.get("language")),
        publisher=_clean(value.get("publisher")),
        published_year=_clean(value.get("publishedYear")),
        abridged=abridged,
        cover=_clean(value.get("cover")),
    )


class AudiobookshelfClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 15.0) -> None:
        cleaned_url = base_url.strip().rstrip("/")
        cleaned_key = api_key.strip()
        if not cleaned_url:
            raise ValueError("Audiobookshelf base URL is required")
        if not cleaned_key:
            raise ValueError("Audiobookshelf API key is required")
        self.base_url = cleaned_url
        self.api_key = cleaned_key
        self.timeout = timeout

    def _url(self, path: str, query: dict[str, object] | None = None) -> str:
        base = self.base_url + "/"
        url = urljoin(base, path.lstrip("/"))
        if query:
            encoded = urlencode({key: str(value) for key, value in query.items() if value is not None})
            url = f"{url}?{encoded}"
        return url

    def _get_json(self, path: str, query: dict[str, object] | None = None) -> Any:
        request = Request(
            self._url(path, query),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "User-Agent": "media-janitor/0.2",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
        except HTTPError as error:
            raise AudiobookshelfError(f"Audiobookshelf returned HTTP {error.code} for {request.full_url}") from error
        except URLError as error:
            raise AudiobookshelfError(f"Could not reach Audiobookshelf at {self.base_url}: {error.reason}") from error
        except OSError as error:
            raise AudiobookshelfError(f"Audiobookshelf request failed: {error}") from error

        try:
            return json.loads(payload)
        except json.JSONDecodeError as error:
            raise AudiobookshelfError("Audiobookshelf returned invalid JSON") from error

    def libraries(self) -> tuple[AudiobookshelfLibrary, ...]:
        payload = self._get_json("api/libraries")
        if isinstance(payload, dict):
            raw_libraries = payload.get("libraries")
        else:
            raw_libraries = payload
        if not isinstance(raw_libraries, list):
            raise AudiobookshelfError("Unexpected Audiobookshelf libraries response")
        return tuple(normalize_library(item) for item in raw_libraries if isinstance(item, dict))

    def library_items(self, library_id: str) -> tuple[AudiobookshelfItem, ...]:
        cleaned_id = library_id.strip()
        if not cleaned_id:
            raise ValueError("Audiobookshelf library id is required")
        payload = self._get_json(
            f"api/libraries/{quote(cleaned_id, safe='')}/items",
            {"limit": 0, "minified": 0, "collapseseries": 0},
        )
        raw_items = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(raw_items, list):
            raise AudiobookshelfError("Unexpected Audiobookshelf library-items response")
        return tuple(normalize_item(item) for item in raw_items if isinstance(item, dict))

    def metadata_providers(self) -> tuple[AudiobookshelfMetadataProvider, ...]:
        payload = self._get_json("api/search/providers")
        providers = payload.get("providers") if isinstance(payload, dict) else None
        raw_books = providers.get("books") if isinstance(providers, dict) else None
        if not isinstance(raw_books, list):
            raise AudiobookshelfError("Unexpected Audiobookshelf metadata-providers response")
        return tuple(normalize_metadata_provider(item) for item in raw_books if isinstance(item, dict))

    def search_books(
        self,
        provider: str,
        title: str,
        author: str | None = None,
        *,
        library_item_id: str | None = None,
    ) -> tuple[ProviderBookResult, ...]:
        clean_provider = provider.strip()
        clean_title = title.strip()
        clean_author = (author or "").strip()
        if not clean_provider:
            raise ValueError("Audiobookshelf metadata provider is required")
        if not clean_title:
            raise ValueError("Book title is required for provider search")

        query: dict[str, object] = {
            "provider": clean_provider,
            "title": clean_title,
            "author": clean_author,
        }
        if library_item_id:
            query["id"] = library_item_id.strip()

        payload = self._get_json("api/search/books", query)
        if not isinstance(payload, list):
            raise AudiobookshelfError("Unexpected Audiobookshelf book-search response")
        return tuple(
            normalize_provider_book(clean_provider, item)
            for item in payload
            if isinstance(item, dict)
        )


def client_from_environment() -> AudiobookshelfClient:
    base_url = os.environ.get("AUDIOBOOKSHELF_URL", "").strip()
    api_key = os.environ.get("AUDIOBOOKSHELF_API_KEY", "").strip()
    if not api_key:
        api_key = os.environ.get("AUDIOBOOKSHELF_TOKEN", "").strip()
    if not base_url:
        raise ValueError("Set AUDIOBOOKSHELF_URL to the Audiobookshelf server URL")
    if not api_key:
        raise ValueError("Set AUDIOBOOKSHELF_API_KEY to an Audiobookshelf API key")
    return AudiobookshelfClient(base_url, api_key)
