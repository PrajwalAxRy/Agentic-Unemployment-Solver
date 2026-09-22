"""Guarded inspection, backup, restore, and reset operations for local state."""

from __future__ import annotations

import os
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from job_finder.persistence.database import CURRENT_SCHEMA_VERSION, current_schema_version


@dataclass(frozen=True, slots=True)
class StateSummary:
    """Content-free state counts safe to show during maintenance."""

    database_path: Path
    schema_version: int
    job_count: int
    pending_count: int
    completed_count: int
    failed_count: int


def inspect_state(path: Path) -> StateSummary:
    """Inspect schema and record counts without creating or migrating state."""
    resolved = _require_file(path, "database")
    connection = _open_read_only(resolved)
    try:
        version = current_schema_version(connection)
        if version != CURRENT_SCHEMA_VERSION:
            raise ValueError(
                f"database schema version is {version}; expected {CURRENT_SCHEMA_VERSION}"
            )
        counts = Counter(
            {
                str(row[0]): int(row[1])
                for row in connection.execute(
                    "SELECT evaluation_status, COUNT(*) FROM jobs GROUP BY evaluation_status"
                )
            }
        )
    finally:
        connection.close()
    return StateSummary(
        database_path=resolved,
        schema_version=version,
        job_count=sum(counts.values()),
        pending_count=counts["pending"],
        completed_count=counts["completed"],
        failed_count=counts["failed"],
    )


def backup_state(database_path: Path, backup_path: Path) -> StateSummary:
    """Create and integrity-check a new SQLite backup without overwriting files."""
    source = _require_file(database_path, "database")
    destination = backup_path.resolve()
    if source == destination:
        raise ValueError("backup path must differ from the database path")
    _reserve_new_file(destination, "backup")

    source_connection = _open_read_only(source)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
        destination_connection.commit()
        _require_integrity(destination_connection, "backup")
    except BaseException:
        destination_connection.close()
        source_connection.close()
        destination.unlink(missing_ok=True)
        raise
    else:
        destination_connection.close()
        source_connection.close()
    return inspect_state(destination)


def restore_state(backup_path: Path, restored_path: Path) -> StateSummary:
    """Restore a verified backup to a new path; existing targets are never overwritten."""
    source = _require_file(backup_path, "backup")
    destination = restored_path.resolve()
    if source == destination:
        raise ValueError("restore target must differ from the backup path")
    _reserve_new_file(destination, "restore target")

    source_connection = _open_read_only(source)
    destination_connection = sqlite3.connect(destination)
    try:
        _require_integrity(source_connection, "backup")
        source_connection.backup(destination_connection)
        destination_connection.commit()
        _require_integrity(destination_connection, "restored database")
    except BaseException:
        destination_connection.close()
        source_connection.close()
        destination.unlink(missing_ok=True)
        raise
    else:
        destination_connection.close()
        source_connection.close()
    return inspect_state(destination)


def reset_state(
    database_path: Path,
    backup_path: Path,
    *,
    confirmation: str,
) -> tuple[StateSummary, StateSummary]:
    """Back up and clear an existing database after exact resolved-path confirmation."""
    database = _require_file(database_path, "database")
    expected_confirmation = str(database)
    if confirmation != expected_confirmation:
        raise ValueError(
            "reset confirmation must exactly match the resolved database path: "
            f"{expected_confirmation}"
        )
    before = backup_state(database, backup_path)
    connection = sqlite3.connect(database, isolation_level=None)
    try:
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM jobs")
        connection.commit()
        connection.execute("VACUUM")
        _require_integrity(connection, "reset database")
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
    return before, inspect_state(database)


def _open_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _require_file(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} does not exist: {resolved}")
    return resolved


def _reserve_new_file(path: Path, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise FileExistsError(f"{label} already exists; refusing to overwrite: {path}") from error
    os.close(descriptor)


def _require_integrity(connection: sqlite3.Connection, label: str) -> None:
    row = connection.execute("PRAGMA integrity_check").fetchone()
    if row is None or row[0] != "ok":
        raise ValueError(f"{label} failed SQLite integrity_check")
