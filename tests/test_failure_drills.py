"""Cross-cutting Phase 10 failure drills and containment assertions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from job_finder.adapters.base import AdapterRegistry
from job_finder.core.company_registry import CompanyRegistryEntry, CompanySourceRegistry
from job_finder.core.job_contracts import DateBasis, NormalizedJob
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
from job_finder.verification import (
    FailureCategory,
    SourceAnomaly,
    VerificationBaseline,
    verify_enabled_sources,
)

NOW = datetime(2026, 9, 23, 12, tzinfo=UTC)


def source(company_id: str) -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id=company_id,
        company_name=company_id.replace("-", " ").title(),
        status=SourceStatus.ENABLED,
        careers_url=f"https://jobs.example.com/{company_id}",
        adapter_type=AdapterType.ASHBY,
        adapter_parameters={"board_name": company_id},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy("publishedAt", DateBasis.PUBLISHED, True, "drill"),
        detail_strategy=DetailStrategy.LISTING_PAYLOAD,
        enabled=True,
        confidence=Confidence.HIGH,
        evidence=(f"https://jobs.example.com/{company_id}",),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def job(company_id: str) -> NormalizedJob:
    return NormalizedJob(
        schema_version=1,
        company_id=company_id,
        source_type="ashby",
        external_job_id=f"{company_id}-1",
        title_original="Machine Learning Engineer",
        title_normalized="machine learning engineer",
        location_original="Bengaluru, India",
        location_normalized=("bengaluru india",),
        published_at=NOW,
        published_at_raw=NOW.isoformat(),
        date_basis=DateBasis.PUBLISHED,
        canonical_url=f"https://jobs.example.com/{company_id}/1",
    )


def result(
    company_source: CompanySource,
    outcome: AdapterOutcome,
    diagnostic: AdapterDiagnostic,
) -> AdapterResult:
    return AdapterResult(
        schema_version=1,
        source=company_source,
        outcome=outcome,
        jobs=(),
        page_count=0,
        complete=False,
        diagnostics=(diagnostic,),
    )


@dataclass(frozen=True)
class FailureDrillAdapter:
    adapter_type: AdapterType = AdapterType.ASHBY

    def list_jobs(self, company_source: CompanySource) -> AdapterResult:
        company_id = company_source.company_id
        if company_id == "healthy":
            return AdapterResult(
                1,
                company_source,
                AdapterOutcome.SUCCESS,
                (job(company_id),),
                1,
                True,
                (),
            )
        if company_id == "collapsed":
            return AdapterResult(1, company_source, AdapterOutcome.EMPTY, (), 1, True, ())
        if company_id == "timeout":
            return result(
                company_source,
                AdapterOutcome.FAILED,
                AdapterDiagnostic(
                    "timeout",
                    DiagnosticSeverity.ERROR,
                    "request timed out",
                    {"retryable": "true"},
                ),
            )
        if company_id == "rate-limited":
            return result(
                company_source,
                AdapterOutcome.FAILED,
                AdapterDiagnostic(
                    "http_error",
                    DiagnosticSeverity.ERROR,
                    "HTTP 429",
                    {"retryable": "true", "status_code": "429"},
                ),
            )
        if company_id == "required-field-removed":
            return result(
                company_source,
                AdapterOutcome.FAILED,
                AdapterDiagnostic(
                    "unsupported_schema",
                    DiagnosticSeverity.ERROR,
                    "required jobs field is missing",
                    {},
                ),
            )
        if company_id == "content-type-changed":
            return result(
                company_source,
                AdapterOutcome.FAILED,
                AdapterDiagnostic(
                    "invalid_content_type",
                    DiagnosticSeverity.ERROR,
                    "unexpected content type",
                    {"status_code": "200"},
                ),
            )
        if company_id == "repeated-page":
            return result(
                company_source,
                AdapterOutcome.SUSPICIOUS,
                AdapterDiagnostic(
                    "repeated_page",
                    DiagnosticSeverity.ERROR,
                    "pagination repeated a page",
                    {},
                ),
            )
        if company_id == "access-blocked":
            return result(
                company_source,
                AdapterOutcome.BLOCKED,
                AdapterDiagnostic(
                    "access_block",
                    DiagnosticSeverity.ERROR,
                    "visible CAPTCHA or login page",
                    {"status_code": "200"},
                ),
            )
        if company_id == "unexpected-error":
            raise RuntimeError("adapter implementation defect with private detail")
        raise AssertionError(f"unknown drill company: {company_id}")


def test_failure_drill_matrix_categorizes_and_contains_every_source() -> None:
    ids = (
        "healthy",
        "collapsed",
        "timeout",
        "rate-limited",
        "required-field-removed",
        "content-type-changed",
        "repeated-page",
        "access-blocked",
        "unexpected-error",
    )
    registry = CompanySourceRegistry(
        schema_version=1,
        registry_version="failure-drills",
        generated_at=NOW,
        discovery_batch_id="failure-drills",
        entries=tuple(
            CompanyRegistryEntry(index, "P1", None, source(company_id))
            for index, company_id in enumerate(ids, start=1)
        ),
    )

    report = verify_enabled_sources(
        registry,
        AdapterRegistry([FailureDrillAdapter()]),
        generated_at=NOW,
        baseline=VerificationBaseline(
            generated_at="2026-09-22T12:00:00+00:00",
            job_counts={"collapsed": 100},
        ),
    )
    records = {record.company_id: record for record in report.records}

    assert len(records) == len(ids)
    assert records["healthy"].outcome == "success"
    assert records["healthy"].failure_categories == ()
    assert records["collapsed"].anomaly_categories == (SourceAnomaly.RESULT_COUNT_COLLAPSE.value,)
    assert records["timeout"].failure_categories == (FailureCategory.TEMPORARY_AVAILABILITY.value,)
    assert records["rate-limited"].failure_categories == (FailureCategory.RATE_LIMIT.value,)
    assert records["required-field-removed"].failure_categories == (
        FailureCategory.SCHEMA_CHANGE.value,
    )
    assert records["content-type-changed"].failure_categories == (
        FailureCategory.SCHEMA_CHANGE.value,
    )
    assert records["repeated-page"].failure_categories == (FailureCategory.PARSER_DEFECT.value,)
    assert records["access-blocked"].failure_categories == (
        FailureCategory.ACCESS_RESTRICTION.value,
    )
    assert records["unexpected-error"].failure_categories == (FailureCategory.PARSER_DEFECT.value,)
    # The last-resort handler now records the concrete exception type alongside the generic
    # label. Recording only "unexpected_adapter_error" made a parser defect indistinguishable
    # from any other unexpected failure (to_change.md 6.2, 9.2).
    (unexpected_category,) = records["unexpected-error"].exception_categories
    assert unexpected_category.startswith("unexpected_adapter_error:")
    assert unexpected_category.split(":", 1)[1]
    assert report.healthy is False
    assert report.company_count == len(ids)


def test_future_date_drill_does_not_discard_the_public_sample_url() -> None:
    company_source = source("future-date")

    @dataclass(frozen=True)
    class FutureAdapter:
        adapter_type: AdapterType = AdapterType.ASHBY

        def list_jobs(self, _: CompanySource) -> AdapterResult:
            listing = replace(job("future-date"), published_at=NOW.replace(year=2028))
            return AdapterResult(
                1,
                company_source,
                AdapterOutcome.SUCCESS,
                (listing,),
                1,
                True,
                (),
            )

    registry = CompanySourceRegistry(
        1,
        "future-drill",
        NOW,
        "failure-drills",
        (CompanyRegistryEntry(1, "P1", None, company_source),),
    )
    report = verify_enabled_sources(
        registry,
        AdapterRegistry([FutureAdapter()]),
        generated_at=NOW,
    )

    record = report.records[0]
    assert record.outcome == "suspicious"
    assert record.anomaly_categories == (SourceAnomaly.FUTURE_PUBLICATION_DATE.value,)
    assert record.sample_job_urls == ("https://jobs.example.com/future-date/1",)
