from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class MediaKind(str, Enum):
    AUDIOBOOK = "audiobook"
    VIDEO = "video"
    OTHER = "other"


class OperationKind(str, Enum):
    MOVE = "move"
    RENAME = "rename"
    MKDIR = "mkdir"
    WRITE_METADATA = "write_metadata"


@dataclass(frozen=True, slots=True)
class FileEntry:
    relative_path: str
    size_bytes: int
    extension: str
    media_kind: MediaKind


@dataclass(frozen=True, slots=True)
class DirectoryContext:
    relative_path: str
    parent: str | None
    sibling_names: tuple[str, ...]
    file_names: tuple[str, ...]
    child_directory_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScanSnapshot:
    root: str
    files: tuple[FileEntry, ...]
    directories: tuple[DirectoryContext, ...]
    unreadable_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FileOperation:
    kind: OperationKind
    source: str | None = None
    destination: str | None = None
    reason: str = ""
    confidence: float | None = None
    evidence: tuple[str, ...] = ()

    def inverse(self) -> "FileOperation | None":
        if self.kind in {OperationKind.MOVE, OperationKind.RENAME} and self.source and self.destination:
            return FileOperation(
                kind=self.kind,
                source=self.destination,
                destination=self.source,
                reason=f"rollback: {self.reason}" if self.reason else "rollback",
                confidence=self.confidence,
                evidence=self.evidence,
            )
        return None


@dataclass(frozen=True, slots=True)
class Plan:
    root: str
    operations: tuple[FileOperation, ...] = field(default_factory=tuple)

    @property
    def rollback_operations(self) -> tuple[FileOperation, ...]:
        inverse = [operation.inverse() for operation in reversed(self.operations)]
        return tuple(operation for operation in inverse if operation is not None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "operations": [asdict(operation) for operation in self.operations],
            "rollback_operations": [asdict(operation) for operation in self.rollback_operations],
        }


def relative_posix(path: Path, root: Path) -> str:
    value = path.relative_to(root).as_posix()
    return value if value != "." else ""
