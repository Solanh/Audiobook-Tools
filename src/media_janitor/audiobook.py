from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class ChapterKind(str, Enum):
    CHAPTER = "chapter"
    PROLOGUE = "prologue"
    EPILOGUE = "epilogue"
    ACKNOWLEDGEMENTS = "acknowledgements"


@dataclass(frozen=True, slots=True)
class ChapterHint:
    kind: ChapterKind
    number: int | None
    matched_text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class NameNormalization:
    original: str
    normalized: str
    transformations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SMALL_NUMBERS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_NUMBER_WORDS = set(_SMALL_NUMBERS) | set(_TENS) | {"and", "hundred", "thousand"}

_RELEASE_NOISE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("unabridged marker", re.compile(r"[\[(]?\bunabridged\b[\])]?", re.IGNORECASE)),
    ("bitrate marker", re.compile(r"[\[(]?\b\d{2,3}\s?k(?:b(?:it)?(?:/s|ps)?)\b[\])]?", re.IGNORECASE)),
    ("codec marker", re.compile(r"[\[(]?\b(?:mp3|m4b|m4a|aac|flac|opus)\b[\])]?", re.IGNORECASE)),
)


def parse_number_words(text: str) -> int | None:
    tokens = [token for token in re.split(r"[^A-Za-z]+", text.lower()) if token]
    if not tokens or any(token not in _NUMBER_WORDS for token in tokens):
        return None

    total = 0
    current = 0
    saw_number = False
    for token in tokens:
        if token == "and":
            continue
        if token in _SMALL_NUMBERS:
            current += _SMALL_NUMBERS[token]
            saw_number = True
        elif token in _TENS:
            current += _TENS[token]
            saw_number = True
        elif token == "hundred":
            current = max(current, 1) * 100
            saw_number = True
        elif token == "thousand":
            total += max(current, 1) * 1000
            current = 0
            saw_number = True

    return total + current if saw_number else None


def extract_chapter_hint(filename: str) -> ChapterHint | None:
    stem = Path(filename).stem

    special_patterns = (
        (ChapterKind.PROLOGUE, re.compile(r"\bprologue\b", re.IGNORECASE)),
        (ChapterKind.EPILOGUE, re.compile(r"\bepilogue\b", re.IGNORECASE)),
        (
            ChapterKind.ACKNOWLEDGEMENTS,
            re.compile(r"\backnowledg(?:e)?ments?\b|\baknowledgements?\b", re.IGNORECASE),
        ),
    )
    for kind, pattern in special_patterns:
        match = pattern.search(stem)
        if match:
            return ChapterHint(kind=kind, number=None, matched_text=match.group(0))

    numeric = re.search(r"\b(?:chapter|chap|ch)\s*[-_.:]?\s*(\d{1,4})\b", stem, re.IGNORECASE)
    if numeric:
        return ChapterHint(
            kind=ChapterKind.CHAPTER,
            number=int(numeric.group(1)),
            matched_text=numeric.group(0),
        )

    word_match = re.search(r"\b(?:chapter|chap|ch)\s+([A-Za-z]+(?:[-\s]+[A-Za-z]+){0,6})", stem, re.IGNORECASE)
    if not word_match:
        return None

    words = re.split(r"[-\s]+", word_match.group(1))
    accepted: list[str] = []
    for word in words:
        if word.lower() not in _NUMBER_WORDS:
            break
        accepted.append(word)

    if not accepted:
        return None

    value = parse_number_words(" ".join(accepted))
    if value is None:
        return None

    prefix = stem[word_match.start() : word_match.start(1)]
    matched_text = prefix + " ".join(accepted)
    return ChapterHint(kind=ChapterKind.CHAPTER, number=value, matched_text=matched_text.strip())


def normalize_search_text(value: str) -> NameNormalization:
    original = value
    stem = Path(value).stem
    normalized = stem
    transformations: list[str] = []

    separator_normalized = re.sub(r"[_]+", " ", normalized)
    separator_normalized = re.sub(r"(?<=\w)\.(?=\w)", " ", separator_normalized)
    if separator_normalized != normalized:
        normalized = separator_normalized
        transformations.append("normalized release separators")

    for description, pattern in _RELEASE_NOISE_PATTERNS:
        cleaned = pattern.sub(" ", normalized)
        if cleaned != normalized:
            normalized = cleaned
            transformations.append(f"removed {description}")

    cleaned = re.sub(r"\s+", " ", normalized).strip(" -_.[]()")
    if cleaned != normalized:
        normalized = cleaned
        transformations.append("collapsed whitespace/punctuation")

    return NameNormalization(
        original=original,
        normalized=normalized,
        transformations=tuple(transformations),
    )
