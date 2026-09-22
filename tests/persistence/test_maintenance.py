"""Tests for guarded state inspection, backup, restore, and reset."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.persistence.database import CURRENT_SCHEMA_VERSION, migrated_database
from job_finder.persistence.maintenance import (
    backup_state,
    inspect_state,
    reset_state,
    restore_state,
)
from job_finder.persistence.repository import JobStateRepository


def _job() -> NormalizedJob:
    return NormalizedJob(
        schema_version=1,
        company_id="example-company",
        source_type="greenhouse",
        external_job_id="REQ-42",
        title_original="ML Engineer",
        title_normalized="ml engineer",
        location_original="Bengaluru",
        location_normalized=("bengaluru",),
        published_at=None,
        published_at_raw=None,
        date_basis=DateBasis.UNKNOWN,
        canonical_url="https://jobs.example.com/REQ-42",
    )


def _database_with_pending_job(path: Path) -> None:
    with migrated_database(path) as connection:
        JobStateRepository(connection).observe_listing(
            _job(),
            observed_at=datetime(2026, 9, 22, tzinfo=UTC),
            profile_version="1.1.0",
        )


def test_inspection_reports_content_free_counts(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"
    _database_with_pending_job(database)

    summary = inspect_state(database)

    assert summary.database_path == database.resolve()
    assert summary.schema_version == CURRENT_SCHEMA_VERSION
    assert summary.job_count == 1
    assert summary.pending_count == 1


def test_backup_and_restore_preserve_records(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"
    backup = tmp_path / "backups" / "jobs-backup.sqlite3"
    restored = tmp_path / "restored" / "jobs.sqlite3"
    _database_with_pending_job(database)

    backup_summary = backup_state(database, backup)
    restored_summary = restore_state(backup, restored)

    assert backup_summary.job_count == 1
    assert restored_summary.job_count == 1
    assert inspect_state(database).job_count == 1


def test_backup_and_restore_refuse_to_overwrite(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    restored = tmp_path / "restored.sqlite3"
    _database_with_pending_job(database)
    backup_state(database, backup)
    restored.touch()

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        backup_state(database, backup)
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        restore_state(backup, restored)


def test_reset_requires_exact_resolved_path_and_creates_backup(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"
    backup = tmp_path / "before-reset.sqlite3"
    _database_with_pending_job(database)

    with pytest.raises(ValueError, match="exactly match"):
        reset_state(database, backup, confirmation="jobs.sqlite3")

    assert inspect_state(database).job_count == 1
    assert not backup.exists()

    before, after = reset_state(database, backup, confirmation=str(database.resolve()))

    assert before.job_count == 1
    assert after.job_count == 0
    assert inspect_state(backup).job_count == 1
