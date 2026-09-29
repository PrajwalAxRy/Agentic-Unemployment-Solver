"""Tests for guarded Phase 8 live validation and H9 reporting."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from job_finder.adapters.base import AdapterRegistry
from job_finder.collection import (
    CandidateSection,
    FilterListingRecord,
    FilterVerificationReport,
    FinalFilterDecision,
)
from job_finder.core.company_registry import CompanyRegistryEntry, CompanySourceRegistry
from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.core.search_profile import load_search_profile
from job_finder.core.source_contracts import (
    AdapterOutcome,
    AdapterResult,
    AdapterType,
    CompanySource,
    Confidence,
    DateStrategy,
    DetailStrategy,
    IdentityStrategy,
    SourceStatus,
)
from job_finder.filters.locations import LocationDecision, LocationFilterResult
from job_finder.filters.roles import RoleDecision, RoleFilterResult
from job_finder.matching.evaluation_set import SeniorityEvaluationExample, SeniorityEvaluationSet
from job_finder.matching.evaluator import (
    EvaluationDisposition,
    EvaluationOutcome,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    ModelPolicy,
    SeniorityEvaluator,
    UsageBudget,
    UsageLimits,
    UsageSnapshot,
)
from job_finder.matching.prompt import load_seniority_prompt
from job_finder.matching.seniority import DetectedLevel, SeniorityDecision, SeniorityMatch
from scripts.phase_gates.seniority_validation import (
    LiveCandidateResult,
    Phase8ValidationReport,
    ReviewedCaseResult,
    collect_live_candidates,
    quality_metrics,
    recollect_live_candidates,
    run_reviewed_evaluation_set,
    write_h9_review,
)

ROOT = Path(__file__).resolve().parents[2]
SCAN_AT = datetime(2026, 9, 23, 12, tzinfo=UTC)


@dataclass
class StubClient:
    contents: list[str]

    def complete(self, request: LLMRequest, policy: ModelPolicy) -> LLMResponse:
        return LLMResponse(self.contents.pop(0), input_tokens=50, output_tokens=20)


@dataclass
class FailingClient:
    def complete(self, request: LLMRequest, policy: ModelPolicy) -> LLMResponse:
        raise LLMProviderError("sanitized provider failure")


def _outcome(match: SeniorityMatch, evidence: str, level: DetectedLevel) -> EvaluationOutcome:
    return EvaluationOutcome(
        disposition=EvaluationDisposition.COMPLETED,
        decision=SeniorityDecision(match, level, "3 years", evidence, "Compared with target."),
        attempt_count=1,
        errors=(),
        usage=UsageSnapshot(1, 100, 50, 20),
        prompt_version="1.0.1",
        model_policy="test:stub:1",
    )


def _reviewed_result(
    case_id: str,
    expected: SeniorityMatch,
    actual: SeniorityMatch,
    level: DetectedLevel = DetectedLevel.MID,
) -> ReviewedCaseResult:
    return ReviewedCaseResult(
        case_id=case_id,
        title="Machine Learning Engineer",
        description="Candidates need 3 years of experience.",
        expected_match=expected,
        expected_level=level,
        important_evidence="3 years of experience",
        human_rationale="Reviewed expectation.",
        outcome=_outcome(actual, "3 years of experience", level),
    )


def test_reviewed_set_runner_and_threshold_measurement() -> None:
    evaluation_set = SeniorityEvaluationSet(
        schema_version=1,
        set_version="test",
        profile_id="profile",
        examples=(
            SeniorityEvaluationExample(
                "case-1",
                "ML Engineer",
                "Candidates need 3 years of experience.",
                True,
                DetectedLevel.MID,
                "Below five years.",
                "3 years of experience",
            ),
        ),
    )
    payload = json.dumps(
        {
            "seniority_match": True,
            "detected_level": "mid",
            "required_experience": "3 years",
            "evidence": "3 years of experience",
            "reason": "The minimum is below five years.",
        }
    )
    evaluator = SeniorityEvaluator(
        client=StubClient([payload]),
        prompt=load_seniority_prompt(ROOT / "config" / "seniority_prompt.toml"),
        model_policy=ModelPolicy("test", "stub", "1"),
        budget=UsageBudget(UsageLimits(5, 10_000, 1_000, 200)),
    )

    results = run_reviewed_evaluation_set(
        evaluation_set,
        evaluator,
        target_description="Open to candidates with fewer than five years.",
    )
    metrics = quality_metrics(results)

    assert metrics.decision_accuracy_percent == 100.0
    assert metrics.recommended_threshold_passed is True


def test_reviewed_set_runner_retains_sanitized_provider_failure() -> None:
    evaluation_set = SeniorityEvaluationSet(
        1,
        "test",
        "profile",
        (
            SeniorityEvaluationExample(
                "case-1",
                "ML Engineer",
                "Candidates need 3 years of experience.",
                True,
                DetectedLevel.MID,
                "Below five years.",
                "3 years of experience",
            ),
        ),
    )
    evaluator = SeniorityEvaluator(
        client=FailingClient(),
        prompt=load_seniority_prompt(ROOT / "config" / "seniority_prompt.toml"),
        model_policy=ModelPolicy("test", "stub", "1"),
        budget=UsageBudget(UsageLimits(5, 10_000, 1_000, 200)),
    )

    results = run_reviewed_evaluation_set(
        evaluation_set,
        evaluator,
        target_description="Open to candidates with fewer than five years.",
    )

    assert results[0].decision is None
    assert results[0].provider_error == "sanitized provider failure"


def test_threshold_rejects_opposite_and_ambiguity_errors() -> None:
    results = (
        _reviewed_result("false-accept", False, True),
        _reviewed_result("false-reject", True, False),
        _reviewed_result("ambiguity", "uncertain", True, DetectedLevel.UNKNOWN),
    )

    metrics = quality_metrics(results)

    assert metrics.false_acceptance_count == 1
    assert metrics.false_rejection_count == 1
    assert metrics.ambiguity_error_count == 1
    assert metrics.recommended_threshold_passed is False


def _source() -> CompanySource:
    return CompanySource(
        1,
        "example",
        "Example",
        SourceStatus.ENABLED,
        "https://jobs.example.com",
        AdapterType.ASHBY,
        {"board_name": "example"},
        IdentityStrategy.EXTERNAL_ID,
        DateStrategy("publishedAt", DateBasis.PUBLISHED, True, "test"),
        DetailStrategy.DETAIL_ENDPOINT,
        True,
        Confidence.HIGH,
        ("https://jobs.example.com",),
        False,
        None,
        "",
    )


def _job(identifier: str) -> NormalizedJob:
    return NormalizedJob(
        1,
        "example",
        "ashby",
        identifier,
        "Machine Learning Engineer",
        "machine learning engineer",
        "Bengaluru, India",
        ("bengaluru india",),
        SCAN_AT,
        SCAN_AT.isoformat(),
        DateBasis.PUBLISHED,
        f"https://jobs.example.com/{identifier}",
    )


def _row(identifier: str, decision: RoleDecision) -> FilterListingRecord:
    return FilterListingRecord(
        "example",
        "Example",
        1,
        "ashby",
        "Machine Learning Engineer",
        "Bengaluru, India",
        f"https://jobs.example.com/{identifier}",
        CandidateSection.STRICT,
        DateBasis.PUBLISHED,
        SCAN_AT.isoformat(),
        RoleFilterResult(decision, "test", "test", "ml_engineering"),
        LocationFilterResult(LocationDecision.PASS, "test", "test", ("india",)),
        FinalFilterDecision.RETAINED,
        _job(identifier),
    )


def _filter_report(rows: tuple[FilterListingRecord, ...]) -> FilterVerificationReport:
    return FilterVerificationReport(
        1,
        SCAN_AT.isoformat(),
        SCAN_AT.isoformat(),
        SCAN_AT.isoformat(),
        "registry",
        "profile",
        "1.1.0",
        "hash",
        1,
        {"success": 1},
        len(rows),
        len(rows),
        0,
        0,
        {},
        {},
        {},
        {},
        {"retained": len(rows)},
        {},
        {},
        (),
        0,
        0,
        (),
        rows,
    )


@dataclass(frozen=True)
class DetailStub:
    adapter_type: AdapterType = AdapterType.ASHBY

    def list_jobs(self, company_source: CompanySource) -> AdapterResult:
        return AdapterResult(
            1,
            company_source,
            AdapterOutcome.SUCCESS,
            (_job("explicit"),),
            1,
            True,
            (),
        )

    def get_job_detail(self, company_source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        description = "Candidates need 3 years of experience building ML services."
        return replace(
            job,
            description=description,
            description_hash=hashlib.sha256(description.encode()).hexdigest(),
        )


def test_live_collection_fetches_details_and_excludes_conditional_titles() -> None:
    source = _source()
    registry = CompanySourceRegistry(
        1,
        "registry",
        SCAN_AT,
        "batch",
        (CompanyRegistryEntry(1, "P1", SCAN_AT, source),),
    )
    report = _filter_report(
        (
            _row("explicit", RoleDecision.EXPLICIT_PASS),
            _row("conditional", RoleDecision.CONDITIONAL_DESCRIPTION),
        )
    )

    selected, issues = collect_live_candidates(
        report,
        registry,
        AdapterRegistry([DetailStub()]),
        load_search_profile(ROOT / "config" / "search_profile.toml"),
        limit=1,
    )

    assert issues == ()
    assert len(selected) == 1
    assert selected[0][0].normalized_job.external_job_id == "explicit"
    assert selected[0][1].description_hash is not None


def test_live_reuse_refreshes_exact_public_candidate(tmp_path: Path) -> None:
    source = _source()
    registry = CompanySourceRegistry(
        1,
        "registry",
        SCAN_AT,
        "batch",
        (CompanyRegistryEntry(1, "P1", SCAN_AT, source),),
    )
    prior = {
        "schema_version": 1,
        "filter_scan_at": SCAN_AT.isoformat(),
        "enabled_company_count": 1,
        "source_outcomes": {"success": 1},
        "source_healthy": True,
        "retained_candidate_count": 2,
        "explicit_candidate_count": 1,
        "conditional_candidate_count": 1,
        "live_candidate_limit": 1,
        "live_cases": [
            {
                "company_name": "Example",
                "title": "Machine Learning Engineer",
                "canonical_url": "https://jobs.example.com/explicit",
                "candidate_section": "strict_recent",
                "role_family": "ml_engineering",
            }
        ],
    }
    path = tmp_path / "prior.json"
    path.write_text(json.dumps(prior), encoding="utf-8")

    evidence, selected, issues = recollect_live_candidates(
        path,
        registry,
        AdapterRegistry([DetailStub()]),
        load_search_profile(ROOT / "config" / "search_profile.toml"),
        source_retry_count=0,
    )

    assert evidence.live_candidate_limit == 1
    assert evidence.source_healthy is True
    assert issues == ()
    assert selected[0][0].role.family_id == "ml_engineering"
    assert selected[0][1].description_hash is not None


def test_h9_review_contains_required_decisions_and_usage(tmp_path: Path) -> None:
    reviewed = (_reviewed_result("case-1", True, True),)
    live_outcome = _outcome("uncertain", "Build ML systems", DetectedLevel.UNKNOWN)
    live = LiveCandidateResult(
        "live-01",
        "Example",
        "ashby",
        "ML Engineer",
        "Bengaluru, India",
        "https://jobs.example.com/1",
        CandidateSection.STRICT,
        "ml_engineering",
        "Build ML systems with the team.",
        live_outcome,
    )
    report = Phase8ValidationReport(
        1,
        SCAN_AT.isoformat(),
        "registry",
        "profile",
        "1.1.0",
        "hash",
        "1.0.0",
        "1.0.1",
        "test:stub:1",
        SCAN_AT.isoformat(),
        1,
        {"success": 1},
        True,
        2,
        1,
        1,
        1,
        (),
        reviewed,
        (live,),
        quality_metrics(reviewed),
        UsageSnapshot(2, 200, 100, 40),
    )
    path = tmp_path / "h9.md"

    write_h9_review(report, path)
    text = path.read_text(encoding="utf-8")

    assert "STOP — Human checkpoint H9" in text
    assert "at least 90% exact agreement" in text
    assert "live-01" in text
    assert "Build ML systems" in text
    assert "Requests: 2" in text
    assert "approve H9 threshold and uncertainty policy" in text
