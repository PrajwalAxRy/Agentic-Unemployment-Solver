"""End-to-end tests for manual scan orchestration and report reconciliation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from job_finder.adapters.base import AdapterRegistry
from job_finder.adapters.http_client import HttpFailureCategory, HttpRequestError
from job_finder.core.company_registry import (
    CompanyRegistryEntry,
    CompanySourceRegistry,
    load_company_registry,
)
from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.core.search_profile import load_search_profile
from job_finder.core.source_contracts import (
    AdapterDiagnostic,
    AdapterOutcome,
    AdapterResult,
    AdapterType,
    CompanySource,
    Confidence,
    DateStrategy,
    DetailStrategy,
    DiagnosticSeverity,
    IdentityStrategy,
    SourceStatus,
)
from job_finder.filter_verification import FilterVerificationReport, verify_filters
from job_finder.matching.evaluator import (
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    ModelPolicy,
    SeniorityEvaluator,
    SeniorityLLMClient,
    UsageBudget,
    UsageLimits,
)
from job_finder.matching.prompt import load_seniority_prompt
from job_finder.persistence.database import migrated_database
from job_finder.persistence.identity import job_identity
from job_finder.persistence.repository import EvaluationStatus, JobStateRepository
from job_finder.reporting.scan_report import render_scan_markdown, write_scan_markdown
from job_finder.scan import (
    SCAN_REPORT_SCHEMA_VERSION,
    ScanOutcome,
    ScanReport,
    _company_accounting,
    process_filter_report,
    run_manual_scan,
    write_scan_report,
)

ROOT = Path(__file__).resolve().parents[1]
SCAN_AT = datetime(2026, 9, 23, 5, 0, tzinfo=UTC)
PROFILE = load_search_profile(ROOT / "config" / "search_profile.toml")


def source(company_id: str, *, reliable_date: bool = True) -> CompanySource:
    return CompanySource(
        1,
        company_id,
        company_id.replace("-", " ").title(),
        SourceStatus.ENABLED,
        f"https://jobs.example.com/{company_id}",
        AdapterType.ASHBY,
        {"board_name": company_id},
        IdentityStrategy.EXTERNAL_ID,
        DateStrategy(
            "publishedAt" if reliable_date else "relative",
            DateBasis.PUBLISHED if reliable_date else DateBasis.UNKNOWN,
            reliable_date,
            "test",
        ),
        DetailStrategy.LISTING_PAYLOAD,
        True,
        Confidence.HIGH,
        (f"https://jobs.example.com/{company_id}",),
        False,
        None,
        "",
    )


def registry(*sources: CompanySource) -> CompanySourceRegistry:
    return CompanySourceRegistry(
        1,
        "test-registry",
        SCAN_AT,
        "test",
        tuple(
            CompanyRegistryEntry(index, "P1", None, company_source)
            for index, company_source in enumerate(sources, start=1)
        ),
    )


def job(
    company_id: str,
    identifier: str,
    title: str,
    description: str | None,
    *,
    uncertain_date: bool = False,
) -> NormalizedJob:
    return NormalizedJob(
        1,
        company_id,
        "ashby",
        identifier,
        title,
        title.casefold(),
        "Bengaluru, India",
        ("bengaluru india",),
        None if uncertain_date else SCAN_AT - timedelta(days=1),
        "2 days ago" if uncertain_date else (SCAN_AT - timedelta(days=1)).isoformat(),
        DateBasis.UNKNOWN if uncertain_date else DateBasis.PUBLISHED,
        f"https://jobs.example.com/{company_id}/{identifier}",
        description,
        hashlib.sha256(description.encode("utf-8")).hexdigest()
        if description is not None
        else None,
    )


@dataclass
class StubAdapter:
    jobs: dict[str, tuple[NormalizedJob, ...]]
    failed: set[str] = field(default_factory=set)
    adapter_type: AdapterType = AdapterType.ASHBY

    def list_jobs(self, company_source: CompanySource) -> AdapterResult:
        if company_source.company_id in self.failed:
            return AdapterResult(
                1,
                company_source,
                AdapterOutcome.FAILED,
                (),
                0,
                False,
                (
                    AdapterDiagnostic(
                        "test_failure",
                        DiagnosticSeverity.ERROR,
                        "simulated source failure",
                        {},
                    ),
                ),
            )
        listings = self.jobs.get(company_source.company_id, ())
        return AdapterResult(
            1,
            company_source,
            AdapterOutcome.SUCCESS if listings else AdapterOutcome.EMPTY,
            listings,
            1,
            True,
            (),
        )


@dataclass
class RetryingDetailAdapter(StubAdapter):
    details: dict[str, NormalizedJob] = field(default_factory=dict)
    failures_remaining: int = 1
    detail_requests: int = 0

    def get_job_detail(
        self, company_source: CompanySource, listing: NormalizedJob
    ) -> NormalizedJob:
        self.detail_requests += 1
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise HttpRequestError(
                HttpFailureCategory.TIMEOUT,
                "sanitized transient detail failure",
                retryable=True,
            )
        return self.details[listing.external_job_id or ""]


@dataclass
class StubLLMClient:
    contents: list[str]
    requests: list[LLMRequest] = field(default_factory=list)

    def complete(self, request: LLMRequest, policy: ModelPolicy) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(self.contents.pop(0), input_tokens=50, output_tokens=20)


@dataclass
class FailingLLMClient:
    requests: list[LLMRequest] = field(default_factory=list)

    def complete(self, request: LLMRequest, policy: ModelPolicy) -> LLMResponse:
        self.requests.append(request)
        raise LLMProviderError("sanitized transient provider failure")


def decision(match: bool | str, *, evidence: str = "3+ years of experience") -> str:
    return json.dumps(
        {
            "seniority_match": match,
            "detected_level": "mid" if match is not False else "senior",
            "required_experience": "3+ years" if match is not False else "7+ years",
            "evidence": evidence,
            "reason": "The description supports this eligibility decision.",
        }
    )


def evaluator(client: SeniorityLLMClient) -> SeniorityEvaluator:
    return SeniorityEvaluator(
        client=client,
        prompt=load_seniority_prompt(ROOT / "config" / "seniority_prompt.toml"),
        model_policy=ModelPolicy("test", "stub", "1"),
        budget=UsageBudget(UsageLimits(20, 20_000, 4_000, 200)),
    )


def filtered(
    test_registry: CompanySourceRegistry,
    adapter: StubAdapter,
) -> FilterVerificationReport:
    return verify_filters(
        test_registry,
        AdapterRegistry([adapter]),
        PROFILE,
        scan_at=SCAN_AT,
        source_retry_count=0,
    )


def process(
    tmp_path: Path,
    test_registry: CompanySourceRegistry,
    adapter: StubAdapter,
    model: SeniorityEvaluator,
    *,
    database_name: str = "jobs.sqlite3",
) -> ScanReport:
    filter_report = filtered(test_registry, adapter)
    database_path = tmp_path / database_name
    with migrated_database(database_path) as connection:
        report = process_filter_report(
            filter_report,
            test_registry,
            AdapterRegistry([adapter]),
            PROFILE,
            model,
            JobStateRepository(connection),
            run_id="scan-test",
            started_at=SCAN_AT,
            completed_at=SCAN_AT + timedelta(minutes=1),
        )
    return report


def test_healthy_match_report_reconciles_and_second_run_suppresses_duplicate(
    tmp_path: Path,
) -> None:
    company = source("healthy")
    description = "Confidential marker. Candidates need 3+ years of experience."
    adapter = StubAdapter(
        {"healthy": (job("healthy", "REQ-1", "Machine Learning Engineer", description),)}
    )
    test_registry = registry(company)
    first_client = StubLLMClient([decision(True)])
    first = process(tmp_path, test_registry, adapter, evaluator(first_client))
    second_client = StubLLMClient([])
    second = process(tmp_path, test_registry, adapter, evaluator(second_client))
    output = tmp_path / "scan.json"
    markdown_output = tmp_path / "scan.md"
    write_scan_report(first, output)
    write_scan_markdown(first, markdown_output)

    assert first.outcome is ScanOutcome.COMPLETE
    assert len(first.matching_jobs) == 1
    assert first.matching_jobs[0].canonical_url.endswith("/REQ-1")
    assert first.matching_jobs[0].seniority_evidence == "3+ years of experience"
    assert first.metrics.canonical_company_count == 1
    assert first.metrics.attempted_company_count == 1
    assert first.metrics.new_identity_count == 1
    assert first.metrics.seniority_match_count == 1
    assert "Confidential marker" not in output.read_text(encoding="utf-8")
    markdown = markdown_output.read_text(encoding="utf-8")
    assert "complete enabled-source coverage" in markdown
    assert "## How to answer the seven review questions" in markdown
    assert "## New matching jobs" in markdown
    assert "3+ years of experience" in markdown
    assert "The description supports this eligibility decision." in markdown
    assert "The default is `reports/latest_scan.json`." in markdown
    assert second.matching_jobs == ()
    assert second.metrics.new_identity_count == 0
    assert second.metrics.duplicate_suppressed_count == 1
    assert second.metrics.llm_cache_hit_count == 1
    assert second_client.requests == []
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        stored = JobStateRepository(connection).get(
            job_identity(adapter.jobs["healthy"][0]).job_key
        )
    assert stored is not None
    assert stored.canonical_url == first.matching_jobs[0].canonical_url
    assert stored.seniority_result is not None
    assert stored.seniority_result["evidence"] == first.matching_jobs[0].seniority_evidence


def test_partial_source_failure_preserves_healthy_results(tmp_path: Path) -> None:
    healthy = source("healthy")
    broken = source("broken")
    adapter = StubAdapter(
        {"healthy": (job("healthy", "REQ-1", "AI Engineer", "Need 3+ years."),)},
        failed={"broken"},
    )
    report = process(
        tmp_path,
        registry(healthy, broken),
        adapter,
        evaluator(StubLLMClient([decision(True, evidence="3+ years")])),
    )

    assert report.outcome is ScanOutcome.PARTIAL
    assert len(report.matching_jobs) == 1
    assert [item.company_id for item in report.source_failures] == ["broken"]
    assert report.metrics.successful_company_count == 1
    assert report.metrics.failed_company_count == 1


def test_complete_source_failure_has_failed_outcome(tmp_path: Path) -> None:
    broken = source("broken")
    adapter = StubAdapter({}, failed={"broken"})
    report = process(
        tmp_path,
        registry(broken),
        adapter,
        evaluator(StubLLMClient([])),
    )

    assert report.outcome is ScanOutcome.FAILED
    assert report.matching_jobs == ()
    assert report.metrics.failed_company_count == 1
    assert report.metrics.successful_company_count == 0
    assert "no enabled source completed successfully" in render_scan_markdown(report)


def test_scan_outcome_exit_statuses_follow_the_declared_contract() -> None:
    assert ScanOutcome.COMPLETE.exit_code == 0
    assert ScanOutcome.PARTIAL.exit_code == 2
    assert ScanOutcome.FAILED.exit_code == 3


def test_complete_registry_accounting_gives_every_disabled_company_a_reason() -> None:
    accounting = _company_accounting(load_company_registry(ROOT / "config/company_sources.json"))

    assert len(accounting) == 330
    assert sum(not item.enabled for item in accounting) == 181
    assert all(item.enabled or item.exception_reason for item in accounting)


def test_healthy_empty_run_clearly_reports_no_new_matches(tmp_path: Path) -> None:
    company = source("empty")
    report = process(
        tmp_path,
        registry(company),
        StubAdapter({}),
        evaluator(StubLLMClient([])),
    )

    markdown = render_scan_markdown(report)
    assert report.outcome is ScanOutcome.COMPLETE
    assert report.metrics.valid_empty_company_count == 1
    assert "No new matching jobs." in markdown
    assert "No enabled source failed." in markdown


def test_uncertain_date_match_and_seniority_uncertainty_are_separate(
    tmp_path: Path,
) -> None:
    company = source("mixed", reliable_date=False)
    adapter = StubAdapter(
        {
            "mixed": (
                job(
                    "mixed",
                    "REQ-1",
                    "AI Engineer",
                    "Candidates need 3+ years of experience.",
                    uncertain_date=True,
                ),
                job(
                    "mixed",
                    "REQ-2",
                    "Machine Learning Engineer",
                    "Build scalable ML systems; no candidate experience requirement is provided.",
                    uncertain_date=True,
                ),
            )
        }
    )
    report = process(
        tmp_path,
        registry(company),
        adapter,
        evaluator(
            StubLLMClient(
                [
                    decision(True),
                    decision(
                        "uncertain",
                        evidence="no candidate experience requirement is provided",
                    ),
                ]
            )
        ),
    )

    assert report.matching_jobs == ()
    assert len(report.date_uncertain_jobs) == 1
    assert report.date_uncertain_jobs[0].date_basis == "unknown"
    assert len(report.review_candidates) == 1
    assert report.review_candidates[0].category == "seniority_uncertain"


def test_conditional_title_without_ai_work_is_terminal_without_llm(tmp_path: Path) -> None:
    company = source("conditional")
    description = "Build and operate payment APIs using Python and PostgreSQL."
    adapter = StubAdapter(
        {"conditional": (job("conditional", "REQ-1", "Software Engineer", description),)}
    )
    test_registry = registry(company)
    first_client = StubLLMClient([])
    first = process(tmp_path, test_registry, adapter, evaluator(first_client))
    second_client = StubLLMClient([])
    second = process(tmp_path, test_registry, adapter, evaluator(second_client))

    assert first.matching_jobs == ()
    assert first.metrics.conditional_rejection_count == 1
    assert first_client.requests == []
    assert second.metrics.duplicate_suppressed_count == 1
    assert second_client.requests == []
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        records = connection.execute("SELECT evaluation_status FROM jobs").fetchall()
    assert [row[0] for row in records] == [EvaluationStatus.FAILED.value]


def test_provider_failure_remains_pending_and_recovers_on_unchanged_run(tmp_path: Path) -> None:
    company = source("healthy")
    listing = job(
        "healthy",
        "REQ-1",
        "Machine Learning Engineer",
        "Candidates need 3+ years of experience.",
    )
    adapter = StubAdapter({"healthy": (listing,)})
    test_registry = registry(company)
    failed_client = FailingLLMClient()

    first = process(tmp_path, test_registry, adapter, evaluator(failed_client))
    second_client = StubLLMClient([decision(True)])
    second = process(tmp_path, test_registry, adapter, evaluator(second_client))

    assert first.matching_jobs == ()
    assert [item.category for item in first.review_candidates] == ["llm_provider_failure"]
    assert len(failed_client.requests) == 1
    assert len(second.matching_jobs) == 1
    assert len(second_client.requests) == 1
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        records = connection.execute("SELECT evaluation_status FROM jobs").fetchall()
    assert [row[0] for row in records] == [EvaluationStatus.COMPLETED.value]


def test_description_failure_remains_pending_and_recovers_on_unchanged_run(tmp_path: Path) -> None:
    company = source("healthy")
    listing = job("healthy", "REQ-1", "Machine Learning Engineer", None)
    detailed = job(
        "healthy",
        "REQ-1",
        "Machine Learning Engineer",
        "Candidates need 3+ years of experience.",
    )
    adapter = RetryingDetailAdapter(
        {"healthy": (listing,)},
        details={"REQ-1": detailed},
    )
    test_registry = registry(company)

    first = process(tmp_path, test_registry, adapter, evaluator(StubLLMClient([])))
    second_client = StubLLMClient([decision(True)])
    second = process(tmp_path, test_registry, adapter, evaluator(second_client))

    assert first.matching_jobs == ()
    assert [item.category for item in first.review_candidates] == ["description_unavailable"]
    assert len(second.matching_jobs) == 1
    assert adapter.detail_requests == 2
    assert len(second_client.requests) == 1
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        records = connection.execute("SELECT evaluation_status FROM jobs").fetchall()
    assert [row[0] for row in records] == [EvaluationStatus.COMPLETED.value]


def test_manual_scan_persists_completed_run_metrics(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    company = source("healthy")
    listing = job(
        "healthy",
        "REQ-1",
        "Machine Learning Engineer",
        "Candidates need 3+ years of experience.",
    )
    listing = replace(
        listing,
        published_at=now - timedelta(days=1),
        published_at_raw=(now - timedelta(days=1)).isoformat(),
    )
    report = run_manual_scan(
        registry(company),
        AdapterRegistry([StubAdapter({"healthy": (listing,)})]),
        PROFILE,
        evaluator(StubLLMClient([decision(True)])),
        database_path=tmp_path / "state" / "jobs.sqlite3",
        lock_path=tmp_path / "state" / "scan.lock",
        source_retry_count=0,
        started_at=now,
        run_id="run-persisted",
    )

    with migrated_database(tmp_path / "state" / "jobs.sqlite3") as connection:
        row = connection.execute(
            "SELECT status, metrics_json FROM scan_runs WHERE run_id = 'run-persisted'"
        ).fetchone()

    assert report.outcome is ScanOutcome.COMPLETE
    assert report.schema_version == SCAN_REPORT_SCHEMA_VERSION
    assert row[0] == "completed"
    assert json.loads(row[1]) == asdict(report.metrics)


def test_manual_scan_reports_bounded_phase_progress(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    company = source("healthy")
    listing = replace(
        job(
            "healthy",
            "REQ-1",
            "Machine Learning Engineer",
            "Candidates need 3+ years of experience.",
        ),
        published_at=now - timedelta(days=1),
        published_at_raw=(now - timedelta(days=1)).isoformat(),
    )
    messages: list[str] = []

    report = run_manual_scan(
        registry(company),
        AdapterRegistry([StubAdapter({"healthy": (listing,)})]),
        PROFILE,
        evaluator(StubLLMClient([decision(True)])),
        database_path=tmp_path / "state" / "jobs.sqlite3",
        lock_path=tmp_path / "state" / "scan.lock",
        source_retry_count=0,
        started_at=now,
        run_id="run-progress",
        progress=messages.append,
    )

    assert report.outcome is ScanOutcome.COMPLETE
    assert messages[0] == "phase=source_collection status=started companies=1"
    assert any("phase=source_collection progress=1/1" in message for message in messages)
    assert any("phase=deterministic_filter progress=1/1" in message for message in messages)
    assert any("phase=candidate_evaluation progress=1/1" in message for message in messages)
    assert messages[-1] == ("phase=candidate_evaluation status=complete observed=1 evaluated=1")
