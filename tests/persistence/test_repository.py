"""Tests for transactional observation and evaluation state."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.persistence.database import migrated_database
from job_finder.persistence.repository import EvaluationStatus, JobStateRepository

OBSERVED_AT = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)
MODEL_POLICY = "test:stub:1"


def make_job(
    *,
    external_job_id: str = "REQ-42",
    description: str | None = None,
) -> NormalizedJob:
    description_hash = (
        hashlib.sha256(description.encode("utf-8")).hexdigest() if description is not None else None
    )
    return NormalizedJob(
        schema_version=1,
        company_id="example-company",
        source_type="greenhouse",
        external_job_id=external_job_id,
        title_original="Machine Learning Engineer",
        title_normalized="machine learning engineer",
        location_original="Bengaluru, India",
        location_normalized=("bengaluru india",),
        published_at=None,
        published_at_raw=None,
        date_basis=DateBasis.UNKNOWN,
        canonical_url=f"https://jobs.example.com/{external_job_id}",
        description=description,
        description_hash=description_hash,
    )


def test_same_listing_observed_twice_has_one_identity(tmp_path: Path) -> None:
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        repository = JobStateRepository(connection)
        first = repository.observe_listing(
            make_job(), observed_at=OBSERVED_AT, profile_version="1.1.0"
        )
        second = repository.observe_listing(
            make_job(),
            observed_at=OBSERVED_AT + timedelta(minutes=5),
            profile_version="1.1.0",
        )

        assert first.is_new is True
        assert second.is_new is False
        assert repository.count() == 1
        assert second.record.first_seen_at == OBSERVED_AT
        assert second.record.last_seen_at == OBSERVED_AT + timedelta(minutes=5)


def test_completed_result_is_reused_for_same_versions_and_description(tmp_path: Path) -> None:
    detailed = make_job(description="Build and deploy ML systems.")
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        repository = JobStateRepository(connection)
        observation = repository.observe_listing(
            make_job(), observed_at=OBSERVED_AT, profile_version="1.1.0"
        )
        preparation = repository.prepare_evaluation(
            detailed,
            profile_version="1.1.0",
            prompt_version="1.0.0",
            model_policy=MODEL_POLICY,
        )
        completed = repository.complete_evaluation(
            observation.record.job_key,
            {"seniority_match": True, "reason": "Two years required."},
        )
        cached = repository.prepare_evaluation(
            detailed,
            profile_version="1.1.0",
            prompt_version="1.0.0",
            model_policy=MODEL_POLICY,
        )

        assert preparation.needs_evaluation is True
        assert completed.evaluation_status is EvaluationStatus.COMPLETED
        assert cached.needs_evaluation is False
        assert cached.record.seniority_result == {
            "reason": "Two years required.",
            "seniority_match": True,
        }


def test_description_change_invalidates_evaluation_but_not_identity(tmp_path: Path) -> None:
    first_detail = make_job(description="Two years of experience required.")
    changed_detail = replace(
        first_detail,
        description="Five years of experience required.",
        description_hash=hashlib.sha256(b"Five years of experience required.").hexdigest(),
    )
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        repository = JobStateRepository(connection)
        observed = repository.observe_listing(
            make_job(), observed_at=OBSERVED_AT, profile_version="1.1.0"
        )
        repository.prepare_evaluation(
            first_detail,
            profile_version="1.1.0",
            prompt_version="1.0.0",
            model_policy=MODEL_POLICY,
        )
        repository.complete_evaluation(observed.record.job_key, {"seniority_match": True})

        changed = repository.prepare_evaluation(
            changed_detail,
            profile_version="1.1.0",
            prompt_version="1.0.0",
            model_policy=MODEL_POLICY,
        )

        assert changed.record.job_key == observed.record.job_key
        assert changed.needs_evaluation is True
        assert changed.record.evaluation_status is EvaluationStatus.PENDING
        assert changed.record.seniority_result is None


@pytest.mark.parametrize(
    ("profile_version", "prompt_version"),
    [("1.2.0", "1.0.0"), ("1.1.0", "1.1.0")],
)
def test_version_change_invalidates_cached_evaluation(
    tmp_path: Path,
    profile_version: str,
    prompt_version: str,
) -> None:
    detailed = make_job(description="Two years of experience required.")
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        repository = JobStateRepository(connection)
        observed = repository.observe_listing(
            make_job(), observed_at=OBSERVED_AT, profile_version="1.1.0"
        )
        repository.prepare_evaluation(
            detailed,
            profile_version="1.1.0",
            prompt_version="1.0.0",
            model_policy=MODEL_POLICY,
        )
        repository.complete_evaluation(observed.record.job_key, {"seniority_match": True})

        changed = repository.prepare_evaluation(
            detailed,
            profile_version=profile_version,
            prompt_version=prompt_version,
            model_policy=MODEL_POLICY,
        )

        assert changed.needs_evaluation is True
        assert changed.record.evaluation_status is EvaluationStatus.PENDING


def test_pending_work_survives_interruption_and_reopen(tmp_path: Path) -> None:
    database_path = tmp_path / "jobs.sqlite3"
    with migrated_database(database_path) as connection:
        repository = JobStateRepository(connection)
        observed = repository.observe_listing(
            make_job(), observed_at=OBSERVED_AT, profile_version="1.1.0"
        )

    with migrated_database(database_path) as connection:
        pending = JobStateRepository(connection).list_pending()

    assert [record.job_key for record in pending] == [observed.record.job_key]


def test_profile_change_during_observation_marks_completed_job_pending(tmp_path: Path) -> None:
    detailed = make_job(description="Two years of experience required.")
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        repository = JobStateRepository(connection)
        observed = repository.observe_listing(
            make_job(), observed_at=OBSERVED_AT, profile_version="1.1.0"
        )
        repository.prepare_evaluation(
            detailed,
            profile_version="1.1.0",
            prompt_version="1.0.0",
            model_policy=MODEL_POLICY,
        )
        repository.complete_evaluation(observed.record.job_key, {"seniority_match": True})

        changed = repository.observe_listing(
            make_job(),
            observed_at=OBSERVED_AT + timedelta(hours=1),
            profile_version="1.2.0",
        )

        assert changed.is_new is False
        assert changed.needs_evaluation is True
        assert changed.record.evaluation_status is EvaluationStatus.PENDING
        assert changed.record.seniority_result is None


def test_model_policy_change_invalidates_cached_evaluation(tmp_path: Path) -> None:
    detailed = make_job(description="Two years of experience required.")
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        repository = JobStateRepository(connection)
        observed = repository.observe_listing(
            make_job(), observed_at=OBSERVED_AT, profile_version="1.1.0"
        )
        repository.prepare_evaluation(
            detailed,
            profile_version="1.1.0",
            prompt_version="1.0.0",
            model_policy=MODEL_POLICY,
        )
        repository.complete_evaluation(observed.record.job_key, {"seniority_match": True})

        changed = repository.prepare_evaluation(
            detailed,
            profile_version="1.1.0",
            prompt_version="1.0.0",
            model_policy="test:new-model:1",
        )

        assert changed.needs_evaluation is True
        assert changed.record.model_policy == "test:new-model:1"
        assert changed.record.evaluation_status is EvaluationStatus.PENDING


def test_completion_requires_prepared_pending_evaluation(tmp_path: Path) -> None:
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        repository = JobStateRepository(connection)
        observed = repository.observe_listing(
            make_job(), observed_at=OBSERVED_AT, profile_version="1.1.0"
        )

        with pytest.raises(
            ValueError, match="missing description, prompt version, or model policy"
        ):
            repository.complete_evaluation(observed.record.job_key, {"seniority_match": True})
