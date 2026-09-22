"""Versioned SQLite database creation and migration."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

CURRENT_SCHEMA_VERSION = 1

_MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (
        """
        CREATE TABLE jobs (
            job_key TEXT PRIMARY KEY,
            company_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            external_job_id TEXT,
            canonical_url TEXT NOT NULL,
            fallback_fingerprint TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            description_hash TEXT,
            profile_version TEXT NOT NULL,
            prompt_version TEXT,
            evaluation_status TEXT NOT NULL
                CHECK (evaluation_status IN ('pending', 'completed', 'failed')),
            seniority_result_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (last_seen_at >= first_seen_at),
            CHECK (
                (evaluation_status = 'completed' AND seniority_result_json IS NOT NULL)
                OR evaluation_status != 'completed'
            )
        )
        """,
        "CREATE INDEX jobs_company_source_idx ON jobs (company_id, source_type)",
        "CREATE INDEX jobs_evaluation_status_idx ON jobs (evaluation_status)",
    ),
}


def open_database(path: Path) -> sqlite3.Connection:
    """Open a local database with integrity-oriented connection settings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


@contextmanager
def migrated_database(path: Path) -> Iterator[sqlite3.Connection]:
    """Open, migrate, and close a database."""
    connection = open_database(path)
    try:
        migrate_database(connection)
        yield connection
    finally:
        connection.close()


def migrate_database(connection: sqlite3.Connection) -> int:
    """Apply every unapplied schema migration in one transaction."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied_versions = {
            int(row[0])
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        }
        unsupported = [version for version in applied_versions if version > CURRENT_SCHEMA_VERSION]
        if unsupported:
            newest = max(unsupported)
            raise ValueError(
                f"database schema version {newest} is newer than supported "
                f"version {CURRENT_SCHEMA_VERSION}"
            )
        missing_older = [
            version
            for version in range(1, max(applied_versions, default=0) + 1)
            if version not in applied_versions
        ]
        if missing_older:
            values = ", ".join(str(version) for version in missing_older)
            raise ValueError(f"database migration history has gaps: {values}")

        for version in range(1, CURRENT_SCHEMA_VERSION + 1):
            if version in applied_versions:
                continue
            for statement in _MIGRATIONS[version]:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, _utc_now_text()),
            )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return current_schema_version(connection)


def current_schema_version(connection: sqlite3.Connection) -> int:
    """Return the newest applied migration, or zero for an uninitialized database."""
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if exists is None:
        return 0
    row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    if row is None or row[0] is None:
        return 0
    return int(row[0])


def _utc_now_text() -> str:
    return datetime.now(UTC).isoformat()
