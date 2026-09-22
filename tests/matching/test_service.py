"""Tests for cache-aware seniority evaluation orchestration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.matching.evaluator import (
    LLMRequest,
    LLMResponse,
    ModelPolicy,
    SeniorityEvaluator,
    UsageBudget,
    UsageLimits,
)
from job_finder.matching.prompt import load_seniority_prompt
from job_finder.matching.service import (
    CachedEvaluationDisposition,
    CachedSeniorityEvaluationService,
    CandidateEligibility,
)
from job_finder.persistence.database import migrated_database
from job_finder.persistence.repository import EvaluationStatus, JobStateRepository

ROOT = Path(__file__).resolve().parents[2]
OBSERVED_AT = datetime(2026, 9, 23, tzinfo=UTC)
TARGET = "Open to candidates with fewer than five years of experience."


def make_job(*, description: str | None = None) -> NormalizedJob:
    return NormalizedJob(
        schema_version=1,
        company_id="example-company",
        source_type="greenhouse",
        external_job_id="REQ-42",
        title_original="Machine Learning Engineer",
        title_normalized="machine learning engineer",
        location_original="Bengaluru, India",
        location_normalized=("bengaluru india",),
        published_at=OBSERVED_AT,
        published_at_raw="2026-09-23",
        date_basis=DateBasis.PUBLISHED,
        canonical_url="https://jobs.example.com/REQ-42",
        description=description,
        description_hash=(
            hashlib.sha256(description.encode()).hexdigest() if description is not None else None
        ),
    )


def valid_response() -> str:
    return json.dumps(
        {
            "seniority_match": True,
            "detected_level": "mid",
            "required_experience": "3+ years",
            "evidence": "3+ years of experience",
            "reason": "The required minimum is below five years.",
        }
    )


@dataclass
class StubClient:
    contents: list[str]
    requests: list[LLMRequest] = field(default_factory=list)

    def complete(self, request: LLMRequest, policy: ModelPolicy) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(self.contents.pop(0), input_tokens=40, output_tokens=20)


def make_evaluator(client: StubClient) -> SeniorityEvaluator:
    return SeniorityEvaluator(
        client=client,
        prompt=load_seniority_prompt(ROOT / "config" / "seniority_prompt.toml"),
        model_policy=ModelPolicy("test", "stub", "1"),
        budget=UsageBudget(UsageLimits(20, 20_000, 4_000, 200)),
    )


@pytest.mark.parametrize(
    "eligibility",
    [
        CandidateEligibility.OLD_LISTING,
        CandidateEligibility.ROLE_REJECTED,
        CandidateEligibility.LOCATION_REJECTED,
    ],
)
def test_ineligible_listing_never_calls_model(
    tmp_path: Path, eligibility: CandidateEligibility
) -> None:
    client = StubClient([])
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        result = CachedSeniorityEvaluationService(
            repository=JobStateRepository(connection),
            evaluator=make_evaluator(client),
        ).evaluate(
            make_job(),
            eligibility=eligibility,
            profile_version="1.1.0",
            target_description=TARGET,
        )

    assert result.disposition is CachedEvaluationDisposition.SKIPPED
    assert client.requests == []


def test_unchanged_completed_job_uses_cache_without_second_call(tmp_path: Path) -> None:
    listing = make_job()
    detailed = replace(
        listing,
        description="Candidates need 3+ years of experience.",
        description_hash=hashlib.sha256(b"Candidates need 3+ years of experience.").hexdigest(),
    )
    client = StubClient([valid_response()])
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        repository = JobStateRepository(connection)
        repository.observe_listing(listing, observed_at=OBSERVED_AT, profile_version="1.1.0")
        service = CachedSeniorityEvaluationService(
            repository=repository,
            evaluator=make_evaluator(client),
        )

        first = service.evaluate(
            detailed,
            eligibility=CandidateEligibility.ELIGIBLE,
            profile_version="1.1.0",
            target_description=TARGET,
        )
        second = service.evaluate(
            detailed,
            eligibility=CandidateEligibility.ELIGIBLE,
            profile_version="1.1.0",
            target_description=TARGET,
        )

    assert first.disposition is CachedEvaluationDisposition.EVALUATED
    assert second.disposition is CachedEvaluationDisposition.CACHED
    assert second.decision == first.decision
    assert len(client.requests) == 1


def test_repeated_invalid_output_remains_pending_for_manual_review(tmp_path: Path) -> None:
    listing = make_job()
    detailed = replace(
        listing,
        description="Candidates need 3+ years of experience.",
        description_hash=hashlib.sha256(b"Candidates need 3+ years of experience.").hexdigest(),
    )
    client = StubClient(["not-json", "still-not-json"])
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        repository = JobStateRepository(connection)
        repository.observe_listing(listing, observed_at=OBSERVED_AT, profile_version="1.1.0")
        result = CachedSeniorityEvaluationService(
            repository=repository,
            evaluator=make_evaluator(client),
        ).evaluate(
            detailed,
            eligibility=CandidateEligibility.ELIGIBLE,
            profile_version="1.1.0",
            target_description=TARGET,
        )

        pending = repository.list_pending()

    assert result.disposition is CachedEvaluationDisposition.MANUAL_REVIEW
    assert len(client.requests) == 2
    assert len(pending) == 1
    assert pending[0].evaluation_status is EvaluationStatus.PENDING
    assert pending[0].seniority_result is None
