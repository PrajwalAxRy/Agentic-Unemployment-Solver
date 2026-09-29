"""Schema migration 4: lifecycle and verdict columns (to_change.md 4.1, 4.2, 9.10).

Added as a numbered migration rather than by dropping and recreating the database. The
execution decision was explicit about this: keep the upgrade path versioned and replayable
on another machine, then wipe row data as a *separate* step.

9.10 fixes the ordering. 6.9 already required the wipe to follow the normalization fix,
because `persistence/identity.py` uses `normalize_title` in the identity hash and Phase 1
re-keys every stored job. Extending that: wipe after these columns land too, or the store
gets re-keyed twice for no benefit. One wipe, immediately before the 5.1 dry-run opens.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import job_finder.persistence.database as database_module
from job_finder.persistence.database import (
    CURRENT_SCHEMA_VERSION,
    current_schema_version,
    migrate_database,
    migrated_database,
    open_database,
)

_LIFECYCLE_COLUMNS = (
    "status",
    "closed_at",
    "consecutive_absences",
    "probe_state",
    "live_but_missing_days",
    "sighting_count",
    "verdict",
    "verdict_at",
    "date_basis",
    "required_experience",
)


def _columns(connection: sqlite3.Connection) -> set[str]:
    return {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}


def _insert_legacy_job(connection: sqlite3.Connection, job_key: str) -> None:
    connection.execute(
        """
        INSERT INTO jobs (
            job_key, company_id, source_type, external_job_id, canonical_url,
            fallback_fingerprint, first_seen_at, last_seen_at, profile_version,
            evaluation_status, created_at, updated_at
        ) VALUES (?, 'google', 'custom', '111', 'https://example.com/1', 'fp',
            '2026-09-01T00:00:00+00:00', '2026-09-29T00:00:00+00:00', '1.1.2',
            'pending', '2026-09-01T00:00:00+00:00', '2026-09-01T00:00:00+00:00')
        """,
        (job_key,),
    )


def test_fresh_database_is_created_at_the_current_version(tmp_path: Path) -> None:
    with migrated_database(tmp_path / "fresh.sqlite3") as connection:
        assert current_schema_version(connection) == CURRENT_SCHEMA_VERSION
        assert _LIFECYCLE_COLUMNS[0] in _columns(connection)
        assert set(_LIFECYCLE_COLUMNS) <= _columns(connection)


def test_existing_database_upgrades_in_place_without_losing_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real store has 859 rows. Upgrading must not be a rebuild.

    This is the test that matters: the wipe is a deliberate separate decision, so the
    migration itself has to be non-destructive even though the rows are about to be
    discarded anyway.
    """
    path = tmp_path / "legacy.sqlite3"

    # Build a database at the pre-lifecycle version.
    monkeypatch.setattr(database_module, "CURRENT_SCHEMA_VERSION", 3)
    with migrated_database(path) as connection:
        _insert_legacy_job(connection, "job-1")
        _insert_legacy_job(connection, "job-2")
        assert current_schema_version(connection) == 3
    monkeypatch.undo()

    with migrated_database(path) as connection:
        assert current_schema_version(connection) == CURRENT_SCHEMA_VERSION
        rows = connection.execute("SELECT * FROM jobs ORDER BY job_key").fetchall()

    assert [row["job_key"] for row in rows] == ["job-1", "job-2"]
    assert rows[0]["first_seen_at"] == "2026-09-01T00:00:00+00:00"


def test_migration_defaults_are_safe_for_rows_with_no_lifecycle_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing rows genuinely have no absence history. Inventing one would be worse.

    sighting_count defaults to 0, which means every pre-existing row is *below* the
    two-sighting guard and cannot be expired until it has been seen twice by the new
    pipeline. That is the conservative direction, and it is deliberate.
    """
    path = tmp_path / "legacy.sqlite3"
    monkeypatch.setattr(database_module, "CURRENT_SCHEMA_VERSION", 3)
    with migrated_database(path) as connection:
        _insert_legacy_job(connection, "job-1")
    monkeypatch.undo()

    with migrated_database(path) as connection:
        row = connection.execute("SELECT * FROM jobs").fetchone()

    assert row["status"] == "active"
    assert row["consecutive_absences"] == 0
    assert row["live_but_missing_days"] == 0
    assert row["sighting_count"] == 0
    # Nullable: absent rather than fabricated.
    assert row["verdict"] is None
    assert row["verdict_at"] is None
    assert row["closed_at"] is None
    assert row["required_experience"] is None


def test_status_column_rejects_unknown_values(tmp_path: Path) -> None:
    with migrated_database(tmp_path / "check.sqlite3") as connection:
        _insert_legacy_job(connection, "job-1")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE jobs SET status = 'archived' WHERE job_key = 'job-1'")


def test_migration_history_is_linear_and_replayable(tmp_path: Path) -> None:
    """A gap in migration history means the upgrade cannot be reproduced elsewhere."""
    path = tmp_path / "history.sqlite3"
    with migrated_database(path):
        pass

    connection = open_database(path)
    try:
        versions = [
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
    finally:
        connection.close()

    assert versions == list(range(1, CURRENT_SCHEMA_VERSION + 1))


def test_migrating_an_already_current_database_is_a_no_op(tmp_path: Path) -> None:
    path = tmp_path / "idempotent.sqlite3"
    with migrated_database(path):
        pass

    connection = open_database(path)
    try:
        assert migrate_database(connection) == CURRENT_SCHEMA_VERSION
        assert migrate_database(connection) == CURRENT_SCHEMA_VERSION
    finally:
        connection.close()
