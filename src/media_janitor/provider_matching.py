from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from .audiobookshelf import ProviderBookResult
from .items import AudiobookItemAnalysis
from .matching import text_similarity


@dataclass(frozen=True, slots=True)
class ProviderEvidence:
    dimension: str
    field: str
    contribution: float
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "field": self.field,
            "contribution": self.contribution,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ProviderCandidateScore:
    result: ProviderBookResult
    identity_score: float
    edition_score: float | None
    evidence: tuple[ProviderEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_score": self.identity_score,
            "edition_score": self.edition_score,
            "provider_result": self.result.to_dict(),
            "evidence": [entry.to_dict() for entry in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class ProviderMatchResult:
    local_item: AudiobookItemAnalysis
    provider: str
    status: str
    candidates: tuple[ProviderCandidateScore, ...]
    identity_margin: float | None
    warnings: tuple[str, ...] = ()

    @property
    def best(self) -> ProviderCandidateScore | None:
        return self.candidates[0] if self.candidates else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status,
            "identity_margin": self.identity_margin,
            "warnings": list(self.warnings),
            "local_item": self.local_item.to_dict(),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def _identifier(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]+", "", (value or "").upper())


def _isbn(value: str | None) -> str:
    return re.sub(r"[^0-9X]+", "", (value or "").upper())


def _best_similarity(left: Iterable[str], right: Iterable[str]) -> float:
    left_values = tuple(left)
    right_values = tuple(right)
    if not left_values or not right_values:
        return 0.0
    return max(text_similarity(a, b) for a in left_values for b in right_values)


def _duration_similarity(local: float | None, provider: float | None) -> tuple[float | None, str | None]:
    if not local or not provider or local <= 0 or provider <= 0:
        return None, None
    delta = abs(local - provider) / max(local, provider)
    if delta <= 0.02:
        return 1.0, f"duration differs by {delta:.1%}"
    if delta <= 0.05:
        return 0.9, f"duration differs by {delta:.1%}"
    if delta <= 0.10:
        return 0.7, f"duration differs by {delta:.1%}"
    if delta <= 0.20:
        return 0.4, f"duration differs by {delta:.1%}"
    if delta <= 0.35:
        return 0.15, f"duration differs by {delta:.1%}"
    return 0.0, f"duration differs substantially ({delta:.1%})"


def score_provider_result(
    local: AudiobookItemAnalysis,
    provider_result: ProviderBookResult,
) -> ProviderCandidateScore:
    evidence: list[ProviderEvidence] = []
    identity = 0.0

    local_asin = _identifier(local.asin)
    result_asin = _identifier(provider_result.asin)
    if local_asin and result_asin:
        if local_asin == result_asin:
            identity += 0.60
            evidence.append(ProviderEvidence("identity", "asin", 0.60, f"exact ASIN match: {local.asin}"))
        else:
            identity -= 0.45
            evidence.append(
                ProviderEvidence(
                    "identity",
                    "asin",
                    -0.45,
                    f"ASIN conflict: {local.asin} vs {provider_result.asin}",
                )
            )

    local_isbn = _isbn(local.isbn)
    result_isbn = _isbn(provider_result.isbn)
    if local_isbn and result_isbn:
        if local_isbn == result_isbn:
            identity += 0.55
            evidence.append(ProviderEvidence("identity", "isbn", 0.55, f"exact ISBN match: {local.isbn}"))
        else:
            identity -= 0.35
            evidence.append(
                ProviderEvidence(
                    "identity",
                    "isbn",
                    -0.35,
                    f"ISBN conflict: {local.isbn} vs {provider_result.isbn}",
                )
            )

    title_similarity = text_similarity(local.title_hint, provider_result.title)
    if title_similarity:
        contribution = 0.42 * title_similarity
        identity += contribution
        evidence.append(
            ProviderEvidence(
                "identity",
                "title",
                contribution,
                f"title similarity {title_similarity:.2f}: {local.title_hint!r} vs {provider_result.title!r}",
            )
        )

    author_similarity = _best_similarity(local.author_hints, provider_result.authors)
    if author_similarity:
        contribution = 0.25 * author_similarity
        identity += contribution
        evidence.append(
            ProviderEvidence("identity", "author", contribution, f"author similarity {author_similarity:.2f}")
        )

    if local.series_hint and provider_result.series:
        series_name, sequence = max(
            provider_result.series,
            key=lambda value: text_similarity(local.series_hint, value[0]),
        )
        series_similarity = text_similarity(local.series_hint, series_name)
        if series_similarity:
            contribution = 0.10 * series_similarity
            identity += contribution
            evidence.append(
                ProviderEvidence("identity", "series", contribution, f"series similarity {series_similarity:.2f}")
            )
            if local.series_index_hint and sequence:
                sequence_match = local.series_index_hint.strip().casefold() == sequence.strip().casefold()
                contribution = 0.04 if sequence_match else -0.04
                identity += contribution
                evidence.append(
                    ProviderEvidence(
                        "identity",
                        "series_sequence",
                        contribution,
                        "series sequence agrees"
                        if sequence_match
                        else f"series sequence conflicts: {local.series_index_hint!r} vs {sequence!r}",
                    )
                )

    identity_score = round(min(max(identity, 0.0), 1.0), 3)

    edition_components: list[tuple[float, float]] = []

    if local_asin and result_asin:
        value = 1.0 if local_asin == result_asin else 0.0
        edition_components.append((0.45, value))
        evidence.append(
            ProviderEvidence(
                "edition",
                "asin",
                0.45 * value,
                "ASIN supports the same audiobook edition" if value else "ASIN indicates a different edition",
            )
        )

    duration_similarity, duration_detail = _duration_similarity(
        local.total_duration_seconds,
        provider_result.duration_seconds,
    )
    if duration_similarity is not None and duration_detail:
        edition_components.append((0.35, duration_similarity))
        evidence.append(
            ProviderEvidence(
                "edition",
                "duration",
                0.35 * duration_similarity,
                duration_detail,
            )
        )

    narrator_similarity = _best_similarity(local.narrator_hints, provider_result.narrators)
    if local.narrator_hints and provider_result.narrators:
        edition_components.append((0.15, narrator_similarity))
        evidence.append(
            ProviderEvidence(
                "edition",
                "narrator",
                0.15 * narrator_similarity,
                f"narrator similarity {narrator_similarity:.2f}",
            )
        )

    if local_isbn and result_isbn:
        value = 1.0 if local_isbn == result_isbn else 0.0
        edition_components.append((0.05, value))
        evidence.append(
            ProviderEvidence(
                "edition",
                "isbn",
                0.05 * value,
                "ISBN agrees" if value else "ISBN differs",
            )
        )

    if edition_components:
        total_weight = sum(weight for weight, _ in edition_components)
        edition_score = round(sum(weight * value for weight, value in edition_components) / total_weight, 3)
    else:
        edition_score = None

    return ProviderCandidateScore(
        result=provider_result,
        identity_score=identity_score,
        edition_score=edition_score,
        evidence=tuple(evidence),
    )


def rank_provider_results(
    local: AudiobookItemAnalysis,
    provider: str,
    results: Iterable[ProviderBookResult],
    *,
    candidate_limit: int = 3,
) -> ProviderMatchResult:
    if candidate_limit < 1:
        raise ValueError("candidate_limit must be at least 1")

    ranked = sorted(
        (score_provider_result(local, result) for result in results),
        key=lambda candidate: (
            -candidate.identity_score,
            -(candidate.edition_score if candidate.edition_score is not None else -1.0),
            candidate.result.provider_id or "",
        ),
    )
    candidates = tuple(ranked[:candidate_limit])
    if not ranked:
        return ProviderMatchResult(
            local_item=local,
            provider=provider,
            status="no_candidate",
            candidates=(),
            identity_margin=None,
        )

    best = ranked[0]
    second_score = ranked[1].identity_score if len(ranked) > 1 else None
    margin = round(best.identity_score - second_score, 3) if second_score is not None else None

    identifier_match = any(
        evidence.dimension == "identity"
        and evidence.field in {"asin", "isbn"}
        and evidence.contribution >= 0.55
        for evidence in best.evidence
    )

    if best.identity_score >= 0.78 and (margin is None or margin >= 0.12):
        status = "strong_identity_candidate"
    elif identifier_match and best.identity_score >= 0.62 and (margin is None or margin >= 0.08):
        status = "strong_identity_candidate"
    elif best.identity_score >= 0.42:
        status = "ambiguous"
    else:
        status = "no_candidate"

    warnings: list[str] = []
    if status == "strong_identity_candidate" and best.edition_score is None:
        warnings.append("book identity is strong but provider data is insufficient to verify the audiobook edition")
    elif status == "strong_identity_candidate" and best.edition_score < 0.65:
        warnings.append("book identity is strong but audiobook-edition evidence is weak or conflicting")

    return ProviderMatchResult(
        local_item=local,
        provider=provider,
        status=status,
        candidates=candidates,
        identity_margin=margin,
        warnings=tuple(warnings),
    )
