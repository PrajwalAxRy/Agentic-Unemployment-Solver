"""Crash and replacement contracts for the database checkpoint."""

from datetime import UTC, datetime

import pytest
from test_scan import PROFILE, SCAN_AT, job

from job_finder.checkpoint import CheckpointError
from job_finder.persistence.batches import BatchRepository, india_date
from job_finder.persistence.database import migrated_database
from job_finder.persistence.identity import job_identity
from job_finder.persistence.repository import JobStateRepository
from job_finder.persistence.transactions import atomic


def test_repository_changes_roll_back_with_batch_transaction(tmp_path):
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        repository = JobStateRepository(connection)
        listing = job("test", "1", "ML Engineer", "Build machine learning")
        with pytest.raises(RuntimeError, match="synthetic crash"), atomic(connection):
            repository.observe_listing(
                listing, observed_at=SCAN_AT, profile_version=PROFILE.version
            )
            raise RuntimeError("synthetic crash")
        assert repository.get(job_identity(listing).job_key) is None


def insert_batch(connection):
    connection.execute(
        "INSERT INTO daily_batch VALUES "
        "(1, 'batch', '2026-10-01', 'attempt', 'eval', 'discovery', 0, '{}', NULL)"
    )
    connection.execute(
        "INSERT INTO batch_candidates(ordinal, job_key, payload_json, is_new) "
        "VALUES (0, 'job', '{}', 1)"
    )
    connection.execute(
        "INSERT INTO llm_requests(request_id, attempt_id, batch_date, requested_at, ordinal, "
        "fingerprint, state, model_policy, input_tokens, output_tokens) "
        "VALUES ('request', 'attempt', '2026-10-01', '2026-10-01T15:00:00+00:00', "
        "0, 'input', 'returned', 'model', 20, 10)"
    )


def test_midnight_rejects_new_invocation_without_destroying_saved_work(tmp_path):
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        insert_batch(connection)
        batches = BatchRepository(connection)
        batches.require_fresh(datetime(2026, 10, 1, 18, 29, 59, tzinfo=UTC))
        with pytest.raises(CheckpointError, match="midnight"):
            batches.require_fresh(datetime(2026, 10, 1, 18, 30, tzinfo=UTC))
        assert len(batches.candidates()) == 1


def test_force_clears_progress_and_marks_spend_without_deleting_batch(tmp_path):
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        insert_batch(connection)
        connection.execute("UPDATE batch_candidates SET result_json = '{}' ")
        batches = BatchRepository(connection)
        batches.restart("new_rules")
        assert batches.current()["evaluation_config"] == "new_rules"
        assert batches.current()["attempt_id"] != "attempt"
        assert batches.candidates()[0]["result_json"] is None
        assert (
            connection.execute("SELECT discarded_reason FROM llm_requests").fetchone()[0]
            == "force_reevaluate"
        )
        batches.discard("new_scan")
        assert not batches.candidates()
        assert connection.execute("SELECT input_tokens FROM llm_requests").fetchone()[0] == 20


def test_india_date_converts_utc_evening():
    assert india_date(datetime(2026, 10, 1, 20, tzinfo=UTC)) == "2026-10-02"
