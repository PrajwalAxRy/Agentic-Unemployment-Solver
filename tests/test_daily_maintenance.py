"""Destructive maintenance uses the scan lock and never destroys spending."""

from datetime import UTC, datetime, timedelta

import pytest

from job_finder.persistence.batches import india_date
from job_finder.persistence.database import migrated_database
from job_finder.persistence.locking import ScanAlreadyRunningError, ScanLock
from job_finder.persistence.maintenance import prune_descriptions, reset_state
from tests.test_daily_scan import run
from tests.test_scan import StubLLMClient, decision


def test_reset_removes_batch_cache_and_history_but_keeps_spending(tmp_path):
    run(tmp_path, StubLLMClient([decision(True)]))
    database = tmp_path / "jobs.sqlite3"
    reset_state(
        database,
        tmp_path / "backup.sqlite3",
        confirmation=str(database.resolve()),
        lock_path=tmp_path / "scan.lock",
    )
    with migrated_database(database) as connection:
        for table in (
            "jobs",
            "daily_batch",
            "batch_candidates",
            "evaluation_cache",
            "daily_observations",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert (
            connection.execute("SELECT discarded_reason FROM llm_requests").fetchone()[0]
            == "state_reset"
        )


def test_prune_protects_current_batch_description_even_if_history_is_old(tmp_path):
    run(tmp_path, StubLLMClient([decision(True)]))
    database = tmp_path / "jobs.sqlite3"
    old = (datetime.now(UTC) - timedelta(days=100)).isoformat()
    with migrated_database(database) as connection:
        connection.execute("UPDATE jobs SET first_seen_at = ?, last_seen_at = ?", (old, old))
        connection.execute(
            "UPDATE daily_batch SET admission_date = ?", (india_date(datetime.now(UTC)),)
        )
    result, _ = prune_descriptions(
        database,
        tmp_path / "backup.sqlite3",
        confirmation=str(database.resolve()),
        lock_path=tmp_path / "scan.lock",
    )
    assert result.rows_cleared == 0
    with migrated_database(database) as connection:
        assert connection.execute("SELECT description FROM jobs").fetchone()[0]
        assert connection.execute("SELECT COUNT(*) FROM batch_candidates").fetchone()[0] == 1


def test_prune_removes_expired_batch_and_keeps_permanent_usage(tmp_path):
    run(tmp_path, StubLLMClient([decision(True)]))
    database = tmp_path / "jobs.sqlite3"
    old = (datetime.now(UTC) - timedelta(days=100)).isoformat()
    with migrated_database(database) as connection:
        connection.execute("UPDATE jobs SET first_seen_at = ?, last_seen_at = ?", (old, old))
        connection.execute("UPDATE daily_batch SET admission_date = '2000-01-01'")
    result, _ = prune_descriptions(
        database,
        tmp_path / "backup.sqlite3",
        confirmation=str(database.resolve()),
        lock_path=tmp_path / "scan.lock",
    )
    assert result.rows_cleared == 1
    with migrated_database(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM daily_batch").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM llm_requests").fetchone()[0] == 1


def test_busy_scan_prevents_prune_before_creating_backup(tmp_path):
    run(tmp_path, StubLLMClient([decision(True)]))
    database = tmp_path / "jobs.sqlite3"
    with ScanLock(tmp_path / "scan.lock"), pytest.raises(ScanAlreadyRunningError):
        prune_descriptions(
            database,
            tmp_path / "backup.sqlite3",
            confirmation=str(database.resolve()),
            lock_path=tmp_path / "scan.lock",
        )
    assert not (tmp_path / "backup.sqlite3").exists()


def test_inspect_distinguishes_attempt_progress_from_completed_history(tmp_path):
    from job_finder.persistence.batches import BatchRepository
    from job_finder.persistence.maintenance import inspect_state

    run(tmp_path, StubLLMClient([decision(True)]))
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        BatchRepository(connection).restart("new_rules")
    summary = inspect_state(tmp_path / "jobs.sqlite3")
    assert summary.completed_count == 1
    assert summary.pending_count == 0
    assert summary.batch_candidate_count == 1
    assert summary.batch_pending_count == 1


def test_legacy_schema_backup_restore_preserves_identity_before_upgrade(tmp_path):
    from job_finder.persistence.maintenance import backup_state, inspect_state, restore_state
    from job_finder.persistence.repository import JobStateRepository
    from tests.test_scan import PROFILE, SCAN_AT, job

    database = tmp_path / "legacy.sqlite3"
    with migrated_database(database) as connection:
        JobStateRepository(connection).observe_listing(
            job("healthy", "1", "ML Engineer", "3+ years of experience"),
            observed_at=SCAN_AT,
            profile_version=PROFILE.version,
        )
        for table in (
            "batch_candidates",
            "daily_batch",
            "evaluation_cache",
            "llm_requests",
            "daily_observations",
            "daily_company_counts",
        ):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("DELETE FROM schema_migrations WHERE version = 6")
    assert inspect_state(database).schema_version == 5
    backup_state(database, tmp_path / "backup.sqlite3")
    restore_state(tmp_path / "backup.sqlite3", tmp_path / "restored.sqlite3")
    with migrated_database(tmp_path / "restored.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert (
            connection.execute("SELECT first_seen_at FROM jobs").fetchone()[0]
            == SCAN_AT.isoformat()
        )
