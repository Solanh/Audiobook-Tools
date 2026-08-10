from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

PLAN_SCHEMA_VERSION = 1
SCAN_SCHEMA_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class MediaKind(str, Enum):
    AUDIOBOOK = "audiobook"
    VIDEO = "video"
    OTHER = "other"


class OperationKind(str, Enum):
    MOVE = "move"
    RENAME = "rename"
    MKDIR = "mkdir"
    RMDIR = "rmdir"
    WRITE_METADATA = "write_metadata"


@dataclass(frozen=True, slots=True)
class FileEntry:
    relative_path: str
    size_bytes: int
    extension: str
    media_kind: MediaKind
    mtime_ns: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "extension": self.extension,
            "media_kind": self.media_kind.value,
            "mtime_ns": self.mtime_ns,
        }


@dataclass(frozen=True, slots=True)
class DirectoryContext:
    relative_path: str
    parent: str | None
    sibling_names: tuple[str, ...]
    file_names: tuple[str, ...]
    child_directory_names: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "parent": self.parent,
            "sibling_names": list(self.sibling_names),
            "file_names": list(self.file_names),
            "child_directory_names": list(self.child_directory_names),
        }


@dataclass(frozen=True, slots=True)
class ScanSnapshot:
    root: str
    files: tuple[FileEntry, ...]
    directories: tuple[DirectoryContext, ...]
    unreadable_paths: tuple[str, ...] = ()
    schema_version: int = SCAN_SCHEMA_VERSION
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "root": self.root,
            "files": [entry.to_dict() for entry in self.files],
            "directories": [context.to_dict() for context in self.directories],
            "unreadable_paths": list(self.unreadable_paths),
        }


@dataclass(frozen=True, slots=True)
class FileOperation:
    kind: OperationKind
    source: str | None = None
    destination: str | None = None
    reason: str = ""
    confidence: float | None = None
    evidence: tuple[str, ...] = ()
    expected_source_size_bytes: int | None = None
    expected_source_mtime_ns: int | None = None
    operation_id: str = field(default_factory=lambda: uuid4().hex)

    @property
    def reversible(self) -> bool:
        return self.inverse() is not None

    def inverse(self) -> "FileOperation | None":
        if self.kind in {OperationKind.MOVE, OperationKind.RENAME} and self.source and self.destination:
            return FileOperation(
                kind=self.kind,
                source=self.destination,
                destination=self.source,
                reason=f"rollback: {self.reason}" if self.reason else "rollback",
                confidence=self.confidence,
                evidence=self.evidence,
                expected_source_size_bytes=self.expected_source_size_bytes,
                expected_source_mtime_ns=self.expected_source_mtime_ns,
                operation_id=f"rollback-{self.operation_id}",
            )
        if self.kind is OperationKind.MKDIR and self.destination:
            return FileOperation(
                kind=OperationKind.RMDIR,
                source=self.destination,
                reason=f"rollback: {self.reason}" if self.reason else "rollback",
                confidence=self.confidence,
                evidence=self.evidence,
                operation_id=f"rollback-{self.operation_id}",
            )
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "kind": self.kind.value,
            "source": self.source,
            "destination": self.destination,
            "reason": self.reason,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "expected_source_size_bytes": self.expected_source_size_bytes,
            "expected_source_mtime_ns": self.expected_source_mtime_ns,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FileOperation":
        return cls(
            kind=OperationKind(value["kind"]),
            source=value.get("source"),
            destination=value.get("destination"),
            reason=value.get("reason", ""),
            confidence=value.get("confidence"),
            evidence=tuple(value.get("evidence", ())),
            expected_source_size_bytes=value.get("expected_source_size_bytes"),
            expected_source_mtime_ns=value.get("expected_source_mtime_ns"),
            operation_id=value.get("operation_id") or uuid4().hex,
        )


@dataclass(frozen=True, slots=True)
class Plan:
    root: str
    operations: tuple[FileOperation, ...] = field(default_factory=tuple)
    plan_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: str = field(default_factory=utc_now_iso)
    schema_version: int = PLAN_SCHEMA_VERSION

    @property
    def rollback_operations(self) -> tuple[FileOperation, ...]:
        inverse = [operation.inverse() for operation in reversed(self.operations)]
        return tuple(operation for operation in inverse if operation is not None)

    @property
    def reversible(self) -> bool:
        return all(operation.reversible for operation in self.operations)

    @property
    def irreversible_operation_ids(self) -> tuple[str, ...]:
        return tuple(operation.operation_id for operation in self.operations if not operation.reversible)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "created_at": self.created_at,
            "root": self.root,
            "operations": [operation.to_dict() for operation in self.operations],
            "rollback_operations": [operation.to_dict() for operation in self.rollback_operations],
            "reversible": self.reversible,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Plan":
        version = int(value.get("schema_version", PLAN_SCHEMA_VERSION))
        if version != PLAN_SCHEMA_VERSION:
            raise ValueError(f"Unsupported plan schema version: {version}")
        return cls(
            root=str(value["root"]),
            operations=tuple(FileOperation.from_dict(item) for item in value.get("operations", ())),
            plan_id=value.get("plan_id") or uuid4().hex,
            created_at=value.get("created_at") or utc_now_iso(),
            schema_version=version,
        )


def relative_posix(path: Path, root: Path) -> str:
    value = path.relative_to(root).as_posix()
    return value if value != "." else ""
