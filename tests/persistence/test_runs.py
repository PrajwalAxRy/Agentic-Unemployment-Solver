"""Tests for durable sanitized scan-run metrics."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from job_finder.persistence.database import migrated_database
from job_finder.persistence.runs import ScanRunRepository, ScanRunStatus

STARTED_AT = datetime(2026, 9, 23, 4, 0, tzinfo=UTC)


def test_scan_run_starts_and_finishes_with_versions_and_metrics(tmp_path: Path) -> None:
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        repository = ScanRunRepository(connection)
        started = repository.start(
            "run-1",
            started_at=STARTED_AT,
            registry_version="1.0.0",
            profile_version="1.1.0",
            prompt_version="1.0.1",
            model_policy="test:stub:v1",
        )
        finished = repository.finish(
            "run-1",
            completed_at=STARTED_AT + timedelta(minutes=2),
            status=ScanRunStatus.COMPLETED,
            metrics={"matches": 2, "coverage_complete": True},
        )

    assert started.status is ScanRunStatus.RUNNING
    assert started.completed_at is None
    assert finished.status is ScanRunStatus.COMPLETED
    assert finished.completed_at == STARTED_AT + timedelta(minutes=2)
    assert finished.metrics == {"coverage_complete": True, "matches": 2}


def test_finished_scan_cannot_be_finished_twice(tmp_path: Path) -> None:
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        repository = ScanRunRepository(connection)
        repository.start(
            "run-1",
            started_at=STARTED_AT,
            registry_version="1.0.0",
            profile_version="1.1.0",
            prompt_version="1.0.1",
            model_policy="test:stub:v1",
        )
        repository.finish(
            "run-1",
            completed_at=STARTED_AT,
            status=ScanRunStatus.PARTIAL,
            metrics={},
        )

        with pytest.raises(ValueError, match="only a running scan"):
            repository.finish(
                "run-1",
                completed_at=STARTED_AT,
                status=ScanRunStatus.FAILED,
                metrics={},
            )


def test_running_status_and_naive_timestamps_are_rejected(tmp_path: Path) -> None:
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        repository = ScanRunRepository(connection)
        with pytest.raises(ValueError, match="timezone-aware"):
            repository.start(
                "run-1",
                started_at=STARTED_AT.replace(tzinfo=None),
                registry_version="1.0.0",
                profile_version="1.1.0",
                prompt_version="1.0.1",
                model_policy="test:stub:v1",
            )

        repository.start(
            "run-2",
            started_at=STARTED_AT,
            registry_version="1.0.0",
            profile_version="1.1.0",
            prompt_version="1.0.1",
            model_policy="test:stub:v1",
        )
        with pytest.raises(ValueError, match="cannot be running"):
            repository.finish(
                "run-2",
                completed_at=STARTED_AT,
                status=ScanRunStatus.RUNNING,
                metrics={},
            )
