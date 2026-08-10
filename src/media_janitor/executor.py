from __future__ import annotations

import os

try:
    import fcntl
except ImportError:  # pragma: no cover - read-only commands still work on non-POSIX hosts
    fcntl = None
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .journal import (
    JournalError,
    create_journal,
    load_journal,
    operation_record,
    set_journal_status,
    set_operation_state,
)
from .models import FileOperation, OperationKind, Plan


class ExecutionError(RuntimeError):
    pass


class UnsafePlanError(ExecutionError):
    pass


class ConcurrentExecutionError(ExecutionError):
    pass


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _root_for_plan(plan: Plan) -> Path:
    root = Path(plan.root).expanduser().resolve()
    if not root.exists():
        raise UnsafePlanError(f"Plan root does not exist: {root}")
    if not root.is_dir():
        raise UnsafePlanError(f"Plan root is not a directory: {root}")
    return root


def _resolve_relative(root: Path, value: str | None, label: str) -> Path:
    if not value:
        raise UnsafePlanError(f"Operation is missing {label}")
    raw = Path(value)
    if raw.is_absolute():
        raise UnsafePlanError(f"{label} must be relative to the plan root: {value}")
    candidate = (root / raw).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise UnsafePlanError(f"{label} escapes the plan root: {value}") from error
    return candidate


def _journal_must_be_outside_root(root: Path, journal_path: Path) -> None:
    resolved = journal_path.expanduser().resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError:
        return
    raise UnsafePlanError(
        "The rollback journal must live outside the media root so a media move cannot move or destroy it"
    )


def validate_plan(plan: Plan) -> None:
    root = _root_for_plan(plan)
    if not plan.operations:
        raise UnsafePlanError("Plan has no operations")
    if not plan.reversible:
        ids = ", ".join(plan.irreversible_operation_ids)
        raise UnsafePlanError(f"Plan contains operations without a rollback definition: {ids}")

    supported = {OperationKind.MOVE, OperationKind.RENAME, OperationKind.MKDIR}
    seen_ids: set[str] = set()
    seen_destinations: set[Path] = set()

    for operation in plan.operations:
        if operation.operation_id in seen_ids:
            raise UnsafePlanError(f"Duplicate operation id: {operation.operation_id}")
        seen_ids.add(operation.operation_id)

        if operation.kind not in supported:
            raise UnsafePlanError(f"Operation kind is not enabled for filesystem apply: {operation.kind.value}")

        if operation.kind in {OperationKind.MOVE, OperationKind.RENAME}:
            source = _resolve_relative(root, operation.source, "source")
            destination = _resolve_relative(root, operation.destination, "destination")
            if source == destination:
                raise UnsafePlanError(f"Operation source and destination are identical: {operation.operation_id}")
            if source.is_dir():
                try:
                    destination.relative_to(source)
                except ValueError:
                    pass
                else:
                    raise UnsafePlanError(f"Cannot move a directory into itself: {operation.operation_id}")
        else:
            destination = _resolve_relative(root, operation.destination, "destination")

        if destination in seen_destinations:
            raise UnsafePlanError(f"Multiple operations target the same destination: {destination}")
        seen_destinations.add(destination)


def _validate_preconditions(root: Path, operation: FileOperation, *, rollback: bool = False) -> None:
    if operation.kind in {OperationKind.MOVE, OperationKind.RENAME}:
        source = _resolve_relative(root, operation.source, "source")
        destination = _resolve_relative(root, operation.destination, "destination")

        if not _lexists(source):
            raise UnsafePlanError(f"Source no longer exists: {source}")
        if source.is_symlink():
            raise UnsafePlanError(f"Refusing to move a symlink as a media operation: {source}")
        if _lexists(destination):
            raise UnsafePlanError(f"Destination already exists; refusing to overwrite it: {destination}")
        if not destination.parent.exists() or not destination.parent.is_dir():
            raise UnsafePlanError(f"Destination parent does not exist: {destination.parent}")

        try:
            source_stat = source.stat()
            source_device = source_stat.st_dev
            destination_device = destination.parent.stat().st_dev
        except OSError as error:
            raise UnsafePlanError(f"Could not inspect move devices: {error}") from error
        if source_device != destination_device:
            raise UnsafePlanError(
                "Cross-filesystem moves are disabled because they are not atomic; "
                f"source={source} destination={destination}"
            )
        if (
            operation.expected_source_size_bytes is not None
            and source_stat.st_size != operation.expected_source_size_bytes
        ):
            raise UnsafePlanError(
                f"Source size changed since the plan was created: {source} "
                f"expected={operation.expected_source_size_bytes} actual={source_stat.st_size}"
            )
        if (
            operation.expected_source_mtime_ns is not None
            and source_stat.st_mtime_ns != operation.expected_source_mtime_ns
        ):
            raise UnsafePlanError(
                f"Source modification time changed since the plan was created: {source}"
            )
        return

    if operation.kind is OperationKind.MKDIR:
        destination = _resolve_relative(root, operation.destination, "destination")
        if _lexists(destination):
            raise UnsafePlanError(f"Directory destination already exists: {destination}")
        if not destination.parent.exists() or not destination.parent.is_dir():
            raise UnsafePlanError(f"Directory parent does not exist: {destination.parent}")
        return

    if operation.kind is OperationKind.RMDIR and rollback:
        source = _resolve_relative(root, operation.source, "source")
        if not source.exists() or not source.is_dir():
            raise UnsafePlanError(f"Rollback directory does not exist: {source}")
        return

    raise UnsafePlanError(f"Unsupported operation during {'rollback' if rollback else 'apply'}: {operation.kind.value}")


def _perform(root: Path, operation: FileOperation, *, rollback: bool = False) -> None:
    _validate_preconditions(root, operation, rollback=rollback)

    if operation.kind in {OperationKind.MOVE, OperationKind.RENAME}:
        source = _resolve_relative(root, operation.source, "source")
        destination = _resolve_relative(root, operation.destination, "destination")
        os.rename(source, destination)
        return

    if operation.kind is OperationKind.MKDIR:
        destination = _resolve_relative(root, operation.destination, "destination")
        destination.mkdir()
        return

    if operation.kind is OperationKind.RMDIR and rollback:
        source = _resolve_relative(root, operation.source, "source")
        source.rmdir()
        return

    raise UnsafePlanError(f"Unsupported operation: {operation.kind.value}")


def _infer_effect(root: Path, operation: FileOperation) -> str:
    if operation.kind in {OperationKind.MOVE, OperationKind.RENAME}:
        source = _resolve_relative(root, operation.source, "source")
        destination = _resolve_relative(root, operation.destination, "destination")
        source_exists = _lexists(source)
        destination_exists = _lexists(destination)
        if source_exists and not destination_exists:
            return "not_applied"
        if not source_exists and destination_exists:
            return "applied"
        return "ambiguous"

    if operation.kind is OperationKind.MKDIR:
        destination = _resolve_relative(root, operation.destination, "destination")
        if not _lexists(destination):
            return "not_applied"
        if destination.is_dir():
            return "applied"
        return "ambiguous"

    return "ambiguous"


@contextmanager
def _exclusive_lock(lock_path: Path) -> Iterator[None]:
    if fcntl is None:
        raise UnsafePlanError("Apply/rollback locking currently requires a POSIX host such as TrueNAS/Linux")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ConcurrentExecutionError(f"Another apply/rollback process holds {lock_path}") from error
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def apply_plan(plan: Plan, journal_path: str | Path, *, confirmed: bool = False) -> dict[str, object]:
    if not confirmed:
        raise UnsafePlanError("Apply requires explicit confirmation")

    validate_plan(plan)
    root = _root_for_plan(plan)
    journal_target = Path(journal_path).expanduser()
    _journal_must_be_outside_root(root, journal_target)
    lock_path = journal_target.parent / ".media-janitor-apply.lock"

    with _exclusive_lock(lock_path):
        journal = create_journal(plan, journal_target)
        set_journal_status(journal_target, journal, "applying")

        for operation in plan.operations:
            set_operation_state(journal_target, journal, operation.operation_id, "applying")
            try:
                _perform(root, operation)
            except Exception as error:
                set_operation_state(
                    journal_target,
                    journal,
                    operation.operation_id,
                    "failed",
                    error=str(error),
                )
                set_journal_status(journal_target, journal, "failed", error=str(error))
                raise

            # This durable state update happens only after the filesystem operation.
            # If the process dies between the rename/mkdir and this write, rollback
            # reconciles the prior "applying" state from the filesystem.
            set_operation_state(journal_target, journal, operation.operation_id, "applied")

        set_journal_status(journal_target, journal, "completed")
        return journal


def _reconcile_interrupted_operation(
    journal_path: Path,
    journal: dict[str, object],
    root: Path,
    operation: FileOperation,
    state: str,
) -> str:
    effect = _infer_effect(root, operation)
    if effect == "ambiguous":
        raise UnsafePlanError(
            f"Cannot safely infer interrupted operation state for {operation.operation_id}; manual review required"
        )

    if state == "applying":
        reconciled_state = "applied" if effect == "applied" else "not_applied"
    elif state == "rolling_back":
        reconciled_state = "applied" if effect == "applied" else "rolled_back"
    else:
        return state

    set_operation_state(
        journal_path,
        journal,
        operation.operation_id,
        reconciled_state,
        event=f"operation_reconciled_{reconciled_state}",
    )
    return reconciled_state


def rollback_journal(journal_path: str | Path, *, confirmed: bool = False) -> dict[str, object]:
    if not confirmed:
        raise UnsafePlanError("Rollback requires explicit confirmation")

    journal_target = Path(journal_path).expanduser()
    journal = load_journal(journal_target)
    plan = Plan.from_dict(journal["plan"])
    root = _root_for_plan(plan)
    _journal_must_be_outside_root(root, journal_target)
    lock_path = journal_target.parent / ".media-janitor-apply.lock"

    with _exclusive_lock(lock_path):
        journal = load_journal(journal_target)
        set_journal_status(journal_target, journal, "rolling_back")

        for operation in reversed(plan.operations):
            record = operation_record(journal, operation.operation_id)
            state = str(record.get("state"))

            if state in {"applying", "rolling_back"}:
                state = _reconcile_interrupted_operation(
                    journal_target,
                    journal,
                    root,
                    operation,
                    state,
                )

            if state in {"pending", "not_applied", "failed", "rolled_back"}:
                continue
            if state != "applied":
                raise JournalError(f"Unknown operation state {state!r} for {operation.operation_id}")

            inverse = operation.inverse()
            if inverse is None:
                raise UnsafePlanError(f"Operation cannot be rolled back: {operation.operation_id}")

            set_operation_state(journal_target, journal, operation.operation_id, "rolling_back")
            try:
                _perform(root, inverse, rollback=True)
            except Exception as error:
                set_journal_status(journal_target, journal, "rollback_failed", error=str(error))
                raise
            set_operation_state(journal_target, journal, operation.operation_id, "rolled_back")

        set_journal_status(journal_target, journal, "rolled_back")
        return journal
