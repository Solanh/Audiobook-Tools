from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import utc_now_iso

STATE_SCHEMA_VERSION = 1
PROPOSAL_STATUSES = {"pending", "approved", "rejected", "ignored"}
FINAL_PROPOSAL_STATUSES = {"approved", "rejected", "ignored"}


class StateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StoredReport:
    report_id: str
    kind: str
    created_at: str
    root: str | None
    payload_sha256: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "kind": self.kind,
            "created_at": self.created_at,
            "root": self.root,
            "payload_sha256": self.payload_sha256,
            "payload": self.payload,
        }


@dataclass(frozen=True, slots=True)
class ProposalRecord:
    proposal_id: str
    source_report_id: str
    local_item_path: str
    status: str
    created_at: str
    updated_at: str
    candidate_sha256: str
    candidate: dict[str, Any]
    decision_note: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "source_report_id": self.source_report_id,
            "local_item_path": self.local_item_path,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "candidate_sha256": self.candidate_sha256,
            "candidate": self.candidate,
            "decision_note": self.decision_note,
        }


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: int
    created_at: str
    event_type: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "created_at": self.created_at,
            "event_type": self.event_type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "payload": self.payload,
        }


def state_database_path(state_dir: str | Path) -> Path:
    return Path(state_dir).expanduser().resolve() / "media-janitor.sqlite3"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _json_digest(payload_json: str) -> str:
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


def _decode_object(payload_json: str, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload_json)
    except json.JSONDecodeError as error:
        raise StateError(f"Stored {label} JSON is corrupt") from error
    if not isinstance(value, dict):
        raise StateError(f"Stored {label} JSON is not an object")
    return value


class StateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()

    @classmethod
    def from_state_dir(cls, state_dir: str | Path) -> "StateStore":
        return cls(state_database_path(state_dir))

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reports (
                    report_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    root TEXT,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS reports_kind_created_idx
                    ON reports(kind, created_at DESC);

                CREATE TABLE IF NOT EXISTS proposals (
                    proposal_id TEXT PRIMARY KEY,
                    source_report_id TEXT NOT NULL,
                    local_item_path TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'ignored')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    candidate_json TEXT NOT NULL,
                    candidate_sha256 TEXT NOT NULL,
                    decision_note TEXT,
                    FOREIGN KEY(source_report_id) REFERENCES reports(report_id) ON DELETE RESTRICT,
                    UNIQUE(source_report_id, local_item_path)
                );

                CREATE INDEX IF NOT EXISTS proposals_status_updated_idx
                    ON proposals(status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS audit_entity_idx
                    ON audit_events(entity_type, entity_id, event_id);
                """
            )
            row = connection.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)",
                    (str(STATE_SCHEMA_VERSION),),
                )
            elif int(row["value"]) != STATE_SCHEMA_VERSION:
                raise StateError(
                    f"Unsupported state schema version {row['value']}; expected {STATE_SCHEMA_VERSION}"
                )

    def _ensure_initialized(self, connection: sqlite3.Connection) -> None:
        try:
            row = connection.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
        except sqlite3.OperationalError as error:
            raise StateError(f"State database is not initialized: {self.path}") from error
        if row is None:
            raise StateError(f"State database is not initialized: {self.path}")
        if int(row["value"]) != STATE_SCHEMA_VERSION:
            raise StateError(
                f"Unsupported state schema version {row['value']}; expected {STATE_SCHEMA_VERSION}"
            )

    def save_report(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        root: str | None = None,
        report_id: str | None = None,
        created_at: str | None = None,
    ) -> StoredReport:
        clean_kind = kind.strip()
        if not clean_kind:
            raise ValueError("report kind is required")
        if not isinstance(payload, dict):
            raise ValueError("report payload must be a JSON object")

        self.initialize()
        report_id = report_id or uuid4().hex
        created_at = created_at or utc_now_iso()
        payload_json = _canonical_json(payload)
        digest = _json_digest(payload_json)

        with self._connect() as connection:
            self._ensure_initialized(connection)
            existing = connection.execute(
                "SELECT payload_sha256 FROM reports WHERE report_id = ?",
                (report_id,),
            ).fetchone()
            if existing is not None:
                if existing["payload_sha256"] != digest:
                    raise StateError(f"Report id {report_id!r} already exists with different content")
                return self.get_report(report_id, connection=connection)

            connection.execute(
                """
                INSERT INTO reports(report_id, kind, created_at, root, payload_json, payload_sha256)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (report_id, clean_kind, created_at, root, payload_json, digest),
            )
            self._append_audit(
                connection,
                event_type="report_saved",
                entity_type="report",
                entity_id=report_id,
                payload={"kind": clean_kind, "root": root, "payload_sha256": digest},
            )

        return StoredReport(report_id, clean_kind, created_at, root, digest, payload)

    def get_report(
        self,
        report_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> StoredReport:
        owns_connection = connection is None
        if connection is None:
            connection = self._connect()
        try:
            self._ensure_initialized(connection)
            row = connection.execute("SELECT * FROM reports WHERE report_id = ?", (report_id,)).fetchone()
            if row is None:
                raise StateError(f"Report not found: {report_id}")
            payload_json = str(row["payload_json"])
            digest = _json_digest(payload_json)
            if digest != row["payload_sha256"]:
                raise StateError(f"Stored report {report_id} failed integrity verification")
            payload = _decode_object(payload_json, label="report")
            return StoredReport(
                report_id=str(row["report_id"]),
                kind=str(row["kind"]),
                created_at=str(row["created_at"]),
                root=row["root"],
                payload_sha256=str(row["payload_sha256"]),
                payload=payload,
            )
        finally:
            if owns_connection:
                connection.close()

    def list_reports(self, *, kind: str | None = None, limit: int = 50) -> tuple[StoredReport, ...]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        self.initialize()
        with self._connect() as connection:
            self._ensure_initialized(connection)
            if kind:
                rows = connection.execute(
                    "SELECT report_id FROM reports WHERE kind = ? ORDER BY created_at DESC LIMIT ?",
                    (kind, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT report_id FROM reports ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return tuple(self.get_report(str(row["report_id"]), connection=connection) for row in rows)

    def stage_proposal(
        self,
        source_report_id: str,
        local_item_path: str,
        candidate: dict[str, Any],
        *,
        proposal_id: str | None = None,
    ) -> ProposalRecord:
        clean_path = local_item_path.strip()
        if not clean_path:
            raise ValueError("local item path is required")
        if not isinstance(candidate, dict):
            raise ValueError("proposal candidate must be a JSON object")

        self.initialize()
        proposal_id = proposal_id or uuid4().hex
        now = utc_now_iso()
        candidate_json = _canonical_json(candidate)
        candidate_digest = _json_digest(candidate_json)

        with self._connect() as connection:
            self._ensure_initialized(connection)
            report = connection.execute(
                "SELECT report_id FROM reports WHERE report_id = ?",
                (source_report_id,),
            ).fetchone()
            if report is None:
                raise StateError(f"Cannot stage proposal from missing report: {source_report_id}")

            existing = connection.execute(
                """
                SELECT proposal_id, candidate_sha256
                FROM proposals
                WHERE source_report_id = ? AND local_item_path = ?
                """,
                (source_report_id, clean_path),
            ).fetchone()
            if existing is not None:
                if existing["candidate_sha256"] != candidate_digest:
                    raise StateError(
                        f"Proposal already exists for {clean_path!r} in report {source_report_id} with different content"
                    )
                return self.get_proposal(str(existing["proposal_id"]), connection=connection)

            connection.execute(
                """
                INSERT INTO proposals(
                    proposal_id, source_report_id, local_item_path, status,
                    created_at, updated_at, candidate_json, candidate_sha256, decision_note
                ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, NULL)
                """,
                (
                    proposal_id,
                    source_report_id,
                    clean_path,
                    now,
                    now,
                    candidate_json,
                    candidate_digest,
                ),
            )
            self._append_audit(
                connection,
                event_type="proposal_staged",
                entity_type="proposal",
                entity_id=proposal_id,
                payload={
                    "source_report_id": source_report_id,
                    "local_item_path": clean_path,
                    "candidate_sha256": candidate_digest,
                },
            )

        return ProposalRecord(
            proposal_id=proposal_id,
            source_report_id=source_report_id,
            local_item_path=clean_path,
            status="pending",
            created_at=now,
            updated_at=now,
            candidate_sha256=candidate_digest,
            candidate=candidate,
            decision_note=None,
        )

    def get_proposal(
        self,
        proposal_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> ProposalRecord:
        owns_connection = connection is None
        if connection is None:
            connection = self._connect()
        try:
            self._ensure_initialized(connection)
            row = connection.execute("SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)).fetchone()
            if row is None:
                raise StateError(f"Proposal not found: {proposal_id}")
            candidate_json = str(row["candidate_json"])
            candidate_digest = _json_digest(candidate_json)
            if candidate_digest != row["candidate_sha256"]:
                raise StateError(f"Stored proposal {proposal_id} failed integrity verification")
            return ProposalRecord(
                proposal_id=str(row["proposal_id"]),
                source_report_id=str(row["source_report_id"]),
                local_item_path=str(row["local_item_path"]),
                status=str(row["status"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
                candidate_sha256=str(row["candidate_sha256"]),
                candidate=_decode_object(candidate_json, label="proposal candidate"),
                decision_note=row["decision_note"],
            )
        finally:
            if owns_connection:
                connection.close()

    def list_proposals(self, *, status: str | None = None, limit: int = 100) -> tuple[ProposalRecord, ...]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if status is not None and status not in PROPOSAL_STATUSES:
            raise ValueError(f"Unknown proposal status: {status}")
        self.initialize()
        with self._connect() as connection:
            self._ensure_initialized(connection)
            if status:
                rows = connection.execute(
                    "SELECT proposal_id FROM proposals WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT proposal_id FROM proposals ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return tuple(self.get_proposal(str(row["proposal_id"]), connection=connection) for row in rows)

    def decide_proposal(self, proposal_id: str, decision: str, *, note: str | None = None) -> ProposalRecord:
        if decision not in FINAL_PROPOSAL_STATUSES:
            raise ValueError(f"Decision must be one of: {', '.join(sorted(FINAL_PROPOSAL_STATUSES))}")
        self.initialize()
        now = utc_now_iso()
        with self._connect() as connection:
            self._ensure_initialized(connection)
            current = self.get_proposal(proposal_id, connection=connection)
            if current.status != "pending":
                if current.status == decision and current.decision_note == note:
                    return current
                raise StateError(
                    f"Proposal {proposal_id} is already {current.status}; decisions are immutable once recorded"
                )

            connection.execute(
                "UPDATE proposals SET status = ?, updated_at = ?, decision_note = ? WHERE proposal_id = ?",
                (decision, now, note, proposal_id),
            )
            self._append_audit(
                connection,
                event_type="proposal_decided",
                entity_type="proposal",
                entity_id=proposal_id,
                payload={
                    "decision": decision,
                    "note": note,
                    "candidate_sha256": current.candidate_sha256,
                },
            )

        return self.get_proposal(proposal_id)

    def list_audit_events(
        self,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        limit: int = 100,
    ) -> tuple[AuditEvent, ...]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        self.initialize()
        clauses: list[str] = []
        params: list[object] = []
        if entity_type:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if entity_id:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as connection:
            self._ensure_initialized(connection)
            rows = connection.execute(
                f"SELECT * FROM audit_events{where} ORDER BY event_id DESC LIMIT ?",
                params,
            ).fetchall()
            return tuple(
                AuditEvent(
                    event_id=int(row["event_id"]),
                    created_at=str(row["created_at"]),
                    event_type=str(row["event_type"]),
                    entity_type=str(row["entity_type"]),
                    entity_id=str(row["entity_id"]),
                    payload=_decode_object(str(row["payload_json"]), label="audit event"),
                )
                for row in rows
            )

    def summary(self) -> dict[str, Any]:
        self.initialize()
        with self._connect() as connection:
            self._ensure_initialized(connection)
            report_count = int(connection.execute("SELECT COUNT(*) FROM reports").fetchone()[0])
            audit_count = int(connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])
            proposal_rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM proposals GROUP BY status"
            ).fetchall()
            return {
                "database": str(self.path),
                "schema_version": STATE_SCHEMA_VERSION,
                "reports": report_count,
                "proposals": {str(row["status"]): int(row["count"]) for row in proposal_rows},
                "audit_events": audit_count,
            }

    def _append_audit(
        self,
        connection: sqlite3.Connection,
        *,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_events(created_at, event_type, entity_type, entity_id, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (utc_now_iso(), event_type, entity_type, entity_id, _canonical_json(payload)),
        )
