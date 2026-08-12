from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from pathlib import PurePosixPath
from typing import Any, Iterable

from .audiobookshelf import AudiobookshelfItem
from .items import AudiobookItemAnalysis


@dataclass(frozen=True, slots=True)
class MatchEvidence:
    field: str
    contribution: float
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "contribution": self.contribution,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class AudiobookMatchCandidate:
    item: AudiobookshelfItem
    score: float
    evidence: tuple[MatchEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "audiobookshelf_item": self.item.to_dict(),
            "evidence": [entry.to_dict() for entry in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class AudiobookMatchResult:
    local_item: AudiobookItemAnalysis
    status: str
    candidates: tuple[AudiobookMatchCandidate, ...]
    margin: float | None
    warnings: tuple[str, ...] = ()

    @property
    def best(self) -> AudiobookMatchCandidate | None:
        return self.candidates[0] if self.candidates else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "margin": self.margin,
            "warnings": list(self.warnings),
            "local_item": self.local_item.to_dict(),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def _fold_text(value: str | None) -> str:
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    asciiish = "".join(character for character in decomposed if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", asciiish))


def text_similarity(left: str | None, right: str | None) -> float:
    a = _fold_text(left)
    b = _fold_text(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    sequence = SequenceMatcher(None, a, b).ratio()
    a_tokens = set(a.split())
    b_tokens = set(b.split())
    if not a_tokens or not b_tokens:
        return sequence

    overlap = len(a_tokens & b_tokens) / min(len(a_tokens), len(b_tokens))
    token_score = overlap * 0.95
    return min(max(sequence, token_score), 1.0)


def _best_name_similarity(left: Iterable[str], right: Iterable[str]) -> float:
    left_values = tuple(left)
    right_values = tuple(right)
    if not left_values or not right_values:
        return 0.0
    return max(text_similarity(a, b) for a in left_values for b in right_values)


def _identifier(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]+", "", (value or "").upper())


def _isbn(value: str | None) -> str:
    return re.sub(r"[^0-9X]+", "", (value or "").upper())


def _normalized_path_segments(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    path = value.replace("\\", "/")
    segments: list[str] = []
    for part in PurePosixPath(path).parts:
        if part in {"/", ".", ".."}:
            continue
        folded = _fold_text(part)
        if folded:
            segments.append(folded)
    return tuple(segments)


def _path_similarity(local_path: str, server_path: str | None) -> tuple[float, str | None]:
    local = _normalized_path_segments(local_path)
    server = _normalized_path_segments(server_path)
    if not local or not server:
        return 0.0, None

    suffix = 0
    for left, right in zip(reversed(local), reversed(server)):
        if left != right:
            break
        suffix += 1

    if suffix >= 2:
        return 0.12, f"last {suffix} path segments agree"
    if suffix == 1:
        return 0.08, "item directory name agrees"

    last_similarity = text_similarity(local[-1], server[-1])
    if last_similarity >= 0.88:
        return 0.05, f"item directory names are similar ({last_similarity:.2f})"
    return 0.0, None


def _duration_contribution(local: float | None, server: float | None) -> tuple[float, str | None]:
    if not local or not server or local <= 0 or server <= 0:
        return 0.0, None
    delta = abs(local - server) / max(local, server)
    if delta <= 0.02:
        return 0.12, f"duration differs by {delta:.1%}"
    if delta <= 0.05:
        return 0.10, f"duration differs by {delta:.1%}"
    if delta <= 0.10:
        return 0.07, f"duration differs by {delta:.1%}"
    if delta <= 0.20:
        return 0.03, f"duration differs by {delta:.1%}"
    if delta >= 0.35:
        return -0.08, f"duration differs substantially ({delta:.1%})"
    return 0.0, f"duration differs by {delta:.1%}"


def score_audiobookshelf_item(
    local: AudiobookItemAnalysis,
    server: AudiobookshelfItem,
) -> AudiobookMatchCandidate:
    evidence: list[MatchEvidence] = []
    score = 0.0

    local_asin = _identifier(local.asin)
    server_asin = _identifier(server.asin)
    if local_asin and server_asin:
        if local_asin == server_asin:
            evidence.append(MatchEvidence("asin", 0.55, f"exact ASIN match: {local.asin}"))
            score += 0.55
        else:
            evidence.append(MatchEvidence("asin", -0.35, f"ASIN conflict: {local.asin} vs {server.asin}"))
            score -= 0.35

    local_isbn = _isbn(local.isbn)
    server_isbn = _isbn(server.isbn)
    if local_isbn and server_isbn:
        if local_isbn == server_isbn:
            evidence.append(MatchEvidence("isbn", 0.50, f"exact ISBN match: {local.isbn}"))
            score += 0.50
        else:
            evidence.append(MatchEvidence("isbn", -0.35, f"ISBN conflict: {local.isbn} vs {server.isbn}"))
            score -= 0.35

    title_similarity = text_similarity(local.title_hint, server.title)
    if title_similarity >= 0.55:
        contribution = 0.30 * title_similarity
        evidence.append(
            MatchEvidence(
                "title",
                contribution,
                f"title similarity {title_similarity:.2f}: {local.title_hint!r} vs {server.title!r}",
            )
        )
        score += contribution
    elif local.title_hint and server.title and title_similarity < 0.30:
        evidence.append(MatchEvidence("title", -0.08, f"titles disagree (similarity {title_similarity:.2f})"))
        score -= 0.08

    author_similarity = _best_name_similarity(local.author_hints, server.authors)
    if author_similarity >= 0.60:
        contribution = 0.18 * author_similarity
        evidence.append(MatchEvidence("author", contribution, f"author similarity {author_similarity:.2f}"))
        score += contribution
    elif local.author_hints and server.authors:
        evidence.append(MatchEvidence("author", -0.08, "author names do not agree"))
        score -= 0.08

    narrator_similarity = _best_name_similarity(local.narrator_hints, server.narrators)
    if narrator_similarity >= 0.70:
        contribution = 0.05 * narrator_similarity
        evidence.append(MatchEvidence("narrator", contribution, f"narrator similarity {narrator_similarity:.2f}"))
        score += contribution

    if local.series_hint and server.series:
        best_series_name, best_sequence = max(
            server.series,
            key=lambda value: text_similarity(local.series_hint, value[0]),
        )
        series_similarity = text_similarity(local.series_hint, best_series_name)
        if series_similarity >= 0.60:
            contribution = 0.08 * series_similarity
            evidence.append(MatchEvidence("series", contribution, f"series similarity {series_similarity:.2f}"))
            score += contribution
            if local.series_index_hint and best_sequence:
                if _fold_text(local.series_index_hint) == _fold_text(best_sequence):
                    evidence.append(MatchEvidence("series_sequence", 0.04, "series sequence agrees"))
                    score += 0.04
                else:
                    evidence.append(
                        MatchEvidence(
                            "series_sequence",
                            -0.04,
                            f"series sequence conflicts: {local.series_index_hint!r} vs {best_sequence!r}",
                        )
                    )
                    score -= 0.04

    duration_score, duration_detail = _duration_contribution(local.total_duration_seconds, server.duration_seconds)
    if duration_detail:
        evidence.append(MatchEvidence("duration", duration_score, duration_detail))
        score += duration_score

    path_score, path_detail = _path_similarity(local.item_path, server.path)
    if path_detail:
        evidence.append(MatchEvidence("path", path_score, path_detail))
        score += path_score

    return AudiobookMatchCandidate(
        item=server,
        score=round(min(max(score, 0.0), 1.0), 3),
        evidence=tuple(evidence),
    )


def match_audiobook_item(
    local: AudiobookItemAnalysis,
    server_items: Iterable[AudiobookshelfItem],
    *,
    candidate_limit: int = 3,
) -> AudiobookMatchResult:
    if candidate_limit < 1:
        raise ValueError("candidate_limit must be at least 1")

    ranked = sorted(
        (score_audiobookshelf_item(local, server) for server in server_items),
        key=lambda candidate: (-candidate.score, candidate.item.id),
    )
    candidates = tuple(ranked[:candidate_limit])
    if not candidates:
        return AudiobookMatchResult(local_item=local, status="no_candidate", candidates=(), margin=None)

    best = ranked[0]
    second_score = ranked[1].score if len(ranked) > 1 else None
    margin = round(best.score - second_score, 3) if second_score is not None else None
    identifier_match = any(
        entry.field in {"asin", "isbn"} and entry.contribution >= 0.50
        for entry in best.evidence
    )

    if best.score >= 0.72 and (margin is None or margin >= 0.12):
        status = "strong_candidate"
    elif identifier_match and best.score >= 0.55 and (margin is None or margin >= 0.08):
        status = "strong_candidate"
    elif best.score >= 0.35:
        status = "ambiguous"
    else:
        status = "no_candidate"

    return AudiobookMatchResult(
        local_item=local,
        status=status,
        candidates=candidates,
        margin=margin,
    )


def match_audiobook_items(
    local_items: Iterable[AudiobookItemAnalysis],
    server_items: Iterable[AudiobookshelfItem],
    *,
    candidate_limit: int = 3,
) -> tuple[AudiobookMatchResult, ...]:
    server_values = tuple(server_items)
    results = [
        match_audiobook_item(local, server_values, candidate_limit=candidate_limit)
        for local in local_items
    ]

    strong_by_server_id: dict[str, list[int]] = defaultdict(list)
    for index, result in enumerate(results):
        if result.status == "strong_candidate" and result.best is not None:
            strong_by_server_id[result.best.item.id].append(index)

    for server_id, indices in strong_by_server_id.items():
        if len(indices) < 2:
            continue
        warning = (
            f"Audiobookshelf item {server_id} is the strong candidate for multiple local items; "
            "manual review is required"
        )
        for index in indices:
            results[index] = replace(
                results[index],
                status="ambiguous",
                warnings=results[index].warnings + (warning,),
            )

    return tuple(results)
