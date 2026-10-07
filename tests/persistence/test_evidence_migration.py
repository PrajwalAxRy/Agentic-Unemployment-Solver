"""Schema migration 5: description text and the discarded LLM judgments.

The merged call returns a validated verbatim quote and a reason for all three of its
judgments, but only the `verdict` enum was ever persisted. That made relevance -- the
judgment that rejects ~59% of evaluated jobs -- the one judgment nobody could audit after
the fact. These columns recover output that was already being paid for.

Nothing here is backfillable. The discarded evidence no longer exists anywhere, so rows
judged before this migration keep NULLs forever. The tests below assert exactly that:
absent rather than fabricated.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import job_finder.persistence.database as database_module
from job_finder.persistence.database import (
    CURRENT_SCHEMA_VERSION,
    current_schema_version,
    migrated_database,
)

_EVIDENCE_COLUMNS = (
    "description",
    "relevance_evidence",
    "relevance_reason",
    "location_evidence",
    "location_reason",
)


def _columns(connection: sqlite3.Connection) -> set[str]:
    return {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}


def _insert_pre_evidence_job(connection: sqlite3.Connection, job_key: str) -> None:
    """Insert using only the column set that existed at migration 4."""
    connection.execute(
        """
        INSERT INTO jobs (
            job_key, company_id, source_type, external_job_id, canonical_url,
            fallback_fingerprint, first_seen_at, last_seen_at, description_hash,
            profile_version, evaluation_status, created_at, updated_at, verdict
        ) VALUES (?, 'google', 'custom', '111', 'https://example.com/1', 'fp',
            '2026-09-01T00:00:00+00:00', '2026-09-29T00:00:00+00:00', 'hash-abc',
            '1.1.2', 'pending', '2026-09-01T00:00:00+00:00',
            '2026-09-01T00:00:00+00:00', 'unrelated')
        """,
        (job_key,),
    )


def test_fresh_database_has_the_evidence_columns(tmp_path: Path) -> None:
    with migrated_database(tmp_path / "fresh.sqlite3") as connection:
        assert current_schema_version(connection) == CURRENT_SCHEMA_VERSION
        assert set(_EVIDENCE_COLUMNS) <= _columns(connection)


def test_existing_database_upgrades_in_place_without_losing_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Migration 4 is already deployed, so 5 must be purely additive."""
    path = tmp_path / "legacy.sqlite3"

    monkeypatch.setattr(database_module, "CURRENT_SCHEMA_VERSION", 4)
    with migrated_database(path) as connection:
        _insert_pre_evidence_job(connection, "job-1")
        _insert_pre_evidence_job(connection, "job-2")
        assert current_schema_version(connection) == 4
    monkeypatch.undo()

    with migrated_database(path) as connection:
        assert current_schema_version(connection) == CURRENT_SCHEMA_VERSION
        rows = connection.execute("SELECT * FROM jobs ORDER BY job_key").fetchall()

    assert [row["job_key"] for row in rows] == ["job-1", "job-2"]
    # The pre-existing verdict and identity survive untouched.
    assert rows[0]["verdict"] == "unrelated"
    assert rows[0]["first_seen_at"] == "2026-09-01T00:00:00+00:00"
    assert rows[0]["description_hash"] == "hash-abc"


def test_already_judged_rows_keep_null_evidence_rather_than_an_invention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The evidence for an old verdict is gone. NULL is the only honest value.

    A row can legitimately carry `verdict = 'unrelated'` with no reason beside it -- that
    pairing means "judged before migration 5", and any consumer rendering evidence has to
    tolerate it rather than assume a verdict implies a quote.
    """
    path = tmp_path / "legacy.sqlite3"
    monkeypatch.setattr(database_module, "CURRENT_SCHEMA_VERSION", 4)
    with migrated_database(path) as connection:
        _insert_pre_evidence_job(connection, "job-1")
    monkeypatch.undo()

    with migrated_database(path) as connection:
        row = connection.execute("SELECT * FROM jobs").fetchone()

    assert row["verdict"] == "unrelated"
    for column in _EVIDENCE_COLUMNS:
        assert row[column] is None, f"{column} must be absent, not fabricated"


def test_migration_8_adds_the_schema_2_columns_and_keeps_old_verdicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Merged prompt 2.0.0 stores a work summary and a location fit beside the verdict.

    Rows judged under 1.x keep their old verdict string and gain NULLs: the 1.x answer had
    no summary or location fit, so there is nothing true to backfill.
    """
    path = tmp_path / "legacy.sqlite3"
    monkeypatch.setattr(database_module, "CURRENT_SCHEMA_VERSION", 7)
    with migrated_database(path) as connection:
        _insert_pre_evidence_job(connection, "job-1")
        assert {"work_summary", "location_fit"}.isdisjoint(_columns(connection))
    monkeypatch.undo()

    with migrated_database(path) as connection:
        assert {"work_summary", "location_fit"} <= _columns(connection)
        row = connection.execute("SELECT * FROM jobs").fetchone()

    assert row["verdict"] == "unrelated"
    assert row["work_summary"] is None
    assert row["location_fit"] is None
