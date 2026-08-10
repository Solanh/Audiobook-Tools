from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .models import Plan, utc_now_iso

JOURNAL_SCHEMA_VERSION = 1


class JournalError(RuntimeError):
    pass


def _fsync_directory(path: Path) -> None:
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    try:
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_journal(path: str | Path, journal: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    journal["updated_at"] = utc_now_iso()

    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(journal, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
        _fsync_directory(target.parent)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def create_journal(plan: Plan, path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if target.exists():
        raise JournalError(f"Journal already exists; refusing to overwrite it: {target}")

    now = utc_now_iso()
    journal: dict[str, Any] = {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "plan": plan.to_dict(),
        "operations": [
            {
                "operation_id": operation.operation_id,
                "state": "pending",
                "error": None,
                "updated_at": now,
            }
            for operation in plan.operations
        ],
        "events": [
            {
                "at": now,
                "event": "journal_created",
                "plan_id": plan.plan_id,
            }
        ],
    }
    write_journal(target, journal)
    return journal


def load_journal(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise JournalError(f"Journal does not exist: {source}") from error
    except json.JSONDecodeError as error:
        raise JournalError(f"Journal is not valid JSON: {source}: {error}") from error

    version = value.get("schema_version")
    if version != JOURNAL_SCHEMA_VERSION:
        raise JournalError(f"Unsupported journal schema version: {version}")
    if not isinstance(value.get("operations"), list) or not isinstance(value.get("plan"), dict):
        raise JournalError(f"Journal is missing required fields: {source}")
    return value


def operation_record(journal: dict[str, Any], operation_id: str) -> dict[str, Any]:
    for record in journal["operations"]:
        if record.get("operation_id") == operation_id:
            return record
    raise JournalError(f"Journal has no record for operation {operation_id}")


def set_operation_state(
    path: str | Path,
    journal: dict[str, Any],
    operation_id: str,
    state: str,
    *,
    error: str | None = None,
    event: str | None = None,
) -> None:
    now = utc_now_iso()
    record = operation_record(journal, operation_id)
    record["state"] = state
    record["error"] = error
    record["updated_at"] = now
    journal["events"].append(
        {
            "at": now,
            "event": event or f"operation_{state}",
            "operation_id": operation_id,
            **({"error": error} if error else {}),
        }
    )
    write_journal(path, journal)


def set_journal_status(
    path: str | Path,
    journal: dict[str, Any],
    status: str,
    *,
    error: str | None = None,
) -> None:
    now = utc_now_iso()
    journal["status"] = status
    journal["events"].append(
        {
            "at": now,
            "event": f"journal_{status}",
            **({"error": error} if error else {}),
        }
    )
    write_journal(path, journal)
