"""Tests for versioned local database migrations."""

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


def test_fresh_database_migrates_to_current_version(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "jobs.sqlite3"

    with migrated_database(database_path) as connection:
        assert current_schema_version(connection) == CURRENT_SCHEMA_VERSION
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }

    assert database_path.is_file()
    assert {"jobs", "scan_runs", "schema_migrations"} <= tables


def test_migration_is_idempotent(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jobs.sqlite3")
    try:
        assert migrate_database(connection) == CURRENT_SCHEMA_VERSION
        first_history = connection.execute(
            "SELECT version, applied_at FROM schema_migrations"
        ).fetchall()

        assert migrate_database(connection) == CURRENT_SCHEMA_VERSION
        second_history = connection.execute(
            "SELECT version, applied_at FROM schema_migrations"
        ).fetchall()
    finally:
        connection.close()

    assert [tuple(row) for row in first_history] == [tuple(row) for row in second_history]


def test_existing_version_zero_database_is_upgraded(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jobs.sqlite3")
    try:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        assert current_schema_version(connection) == 0

        assert migrate_database(connection) == CURRENT_SCHEMA_VERSION
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    finally:
        connection.close()


def test_version_one_database_adds_model_policy_without_losing_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = open_database(tmp_path / "jobs.sqlite3")
    try:
        monkeypatch.setattr(database_module, "CURRENT_SCHEMA_VERSION", 1)
        migrate_database(connection)
        connection.execute(
            """
            INSERT INTO jobs (
                job_key, company_id, source_type, canonical_url, fallback_fingerprint,
                first_seen_at, last_seen_at, profile_version, evaluation_status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "job-key",
                "company",
                "greenhouse",
                "https://example.com/jobs/1",
                "fallback",
                "2026-09-22T00:00:00+00:00",
                "2026-09-22T00:00:00+00:00",
                "1.1.0",
                "pending",
                "2026-09-22T00:00:00+00:00",
                "2026-09-22T00:00:00+00:00",
            ),
        )

        monkeypatch.setattr(database_module, "CURRENT_SCHEMA_VERSION", 2)
        assert migrate_database(connection) == 2
        row = connection.execute(
            "SELECT job_key, model_policy FROM jobs WHERE job_key = 'job-key'"
        ).fetchone()
    finally:
        connection.close()

    assert tuple(row) == ("job-key", None)


def test_newer_database_version_is_rejected_without_changes(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jobs.sqlite3")
    try:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (CURRENT_SCHEMA_VERSION + 1, "2026-09-22T00:00:00+00:00"),
        )

        with pytest.raises(ValueError, match="newer than supported"):
            migrate_database(connection)

        jobs_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
        ).fetchone()
    finally:
        connection.close()

    assert jobs_table is None


def test_job_constraints_reject_completed_record_without_result(tmp_path: Path) -> None:
    with (
        migrated_database(tmp_path / "jobs.sqlite3") as connection,
        pytest.raises(sqlite3.IntegrityError),
    ):
        connection.execute(
            """
                INSERT INTO jobs (
                    job_key, company_id, source_type, canonical_url, fallback_fingerprint,
                    first_seen_at, last_seen_at, profile_version, evaluation_status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
            (
                "job-key",
                "company",
                "greenhouse",
                "https://example.com/jobs/1",
                "fallback",
                "2026-09-22T00:00:00+00:00",
                "2026-09-22T00:00:00+00:00",
                "1.1.0",
                "completed",
                "2026-09-22T00:00:00+00:00",
                "2026-09-22T00:00:00+00:00",
            ),
        )
