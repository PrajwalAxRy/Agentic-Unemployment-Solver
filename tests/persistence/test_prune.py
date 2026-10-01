"""Tests for the description sweep.

The central claim under test is that pruning nulls a column and never deletes a row.
`collection.py` reads `jobs.first_seen_at` as the recency basis whenever a source lacks a
verified publication date, so deleting a row makes a still-live job look newly-seen: it
re-enters the funnel, is re-evaluated at cost, and resurfaces in the report as new.
Deleting would also bypass the two-sighting and collapse-ratio guards in `core.lifecycle`.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.persistence.database import migrated_database
from job_finder.persistence.maintenance import prune_descriptions
from job_finder.persistence.repository import JobStateRepository

DESCRIPTION = "Build and operate production ML systems. 3+ years of experience required."


def _job(identifier: str = "REQ-42", *, described: bool = False) -> NormalizedJob:
    return NormalizedJob(
        schema_version=1,
        company_id="example-company",
        source_type="greenhouse",
        external_job_id=identifier,
        title_original="ML Engineer",
        title_normalized="ml engineer",
        location_original="Bengaluru",
        location_normalized=("bengaluru",),
        published_at=None,
        published_at_raw=None,
        date_basis=DateBasis.UNKNOWN,
        canonical_url=f"https://jobs.example.com/{identifier}",
        description=DESCRIPTION if described else None,
        description_hash=(
            hashlib.sha256(DESCRIPTION.encode("utf-8")).hexdigest() if described else None
        ),
    )


def _seed(path: Path, *, identifier: str, last_seen: datetime) -> str:
    """Observe and prepare one job so it carries stored description text."""
    with migrated_database(path) as connection:
        repository = JobStateRepository(connection)
        observation = repository.observe_listing(
            _job(identifier),
            observed_at=last_seen,
            profile_version="1.1.0",
        )
        repository.prepare_evaluation(
            _job(identifier, described=True),
            profile_version="1.1.0",
            prompt_version="1.0.0",
            model_policy="test:stub:1",
        )
        return observation.record.job_key


def _confirm(path: Path) -> str:
    return str(path.resolve())


def test_stale_descriptions_are_cleared(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"
    key = _seed(database, identifier="OLD-1", last_seen=datetime.now(UTC) - timedelta(days=200))

    result, _ = prune_descriptions(
        database,
        tmp_path / "backup.sqlite3",
        confirmation=_confirm(database),
        older_than_days=90,
    )

    assert result.rows_cleared == 1
    with migrated_database(database) as connection:
        record = JobStateRepository(connection).require(key)
    assert record.description is None


def test_pruning_keeps_the_row_and_everything_the_pipeline_depends_on(tmp_path: Path) -> None:
    """Deleting would make a still-live job look newly-seen and be re-evaluated at cost."""
    database = tmp_path / "jobs.sqlite3"
    first_seen = datetime.now(UTC) - timedelta(days=200)
    key = _seed(database, identifier="OLD-1", last_seen=first_seen)

    prune_descriptions(
        database,
        tmp_path / "backup.sqlite3",
        confirmation=_confirm(database),
        older_than_days=90,
    )

    with migrated_database(database) as connection:
        repository = JobStateRepository(connection)
        assert repository.count() == 1, "the row must survive"
        record = repository.require(key)

    assert record.first_seen_at == first_seen, "the recency basis must survive"
    assert record.description_hash is not None, "the evaluation cache key must survive"
    assert record.profile_version == "1.1.0"


def test_a_recently_seen_job_is_untouched_however_old_it_is(tmp_path: Path) -> None:
    """Filtering on first_seen_at would clear a long-running job that is still live."""
    database = tmp_path / "jobs.sqlite3"
    key = _seed(database, identifier="LIVE-1", last_seen=datetime.now(UTC) - timedelta(days=2))

    result, _ = prune_descriptions(
        database,
        tmp_path / "backup.sqlite3",
        confirmation=_confirm(database),
        older_than_days=90,
    )

    assert result.rows_cleared == 0
    with migrated_database(database) as connection:
        assert JobStateRepository(connection).require(key).description == DESCRIPTION


def test_pruning_requires_the_exact_resolved_path(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"
    _seed(database, identifier="OLD-1", last_seen=datetime.now(UTC) - timedelta(days=200))

    with pytest.raises(ValueError, match="must exactly match the resolved database path"):
        prune_descriptions(
            database,
            tmp_path / "backup.sqlite3",
            confirmation="state/jobs.sqlite3",
        )


def test_a_backup_is_taken_before_anything_is_cleared(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    key = _seed(database, identifier="OLD-1", last_seen=datetime.now(UTC) - timedelta(days=200))

    prune_descriptions(database, backup, confirmation=_confirm(database), older_than_days=90)

    assert backup.is_file()
    with migrated_database(backup) as connection:
        assert JobStateRepository(connection).require(key).description == DESCRIPTION


def test_a_zero_day_window_is_refused(tmp_path: Path) -> None:
    """`--older-than-days 0` would clear every description including this run's."""
    database = tmp_path / "jobs.sqlite3"
    _seed(database, identifier="OLD-1", last_seen=datetime.now(UTC) - timedelta(days=200))

    with pytest.raises(ValueError, match="at least 1"):
        prune_descriptions(
            database,
            tmp_path / "backup.sqlite3",
            confirmation=_confirm(database),
            older_than_days=0,
        )
