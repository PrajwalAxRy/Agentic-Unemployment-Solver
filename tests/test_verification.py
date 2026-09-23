"""Tests for read-only source-verification reporting."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

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
    load_verification_baseline,
    verify_adapter_sources,
    verify_enabled_sources,
    write_verification_report,
)


def source(company_id: str, company_name: str) -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id=company_id,
        company_name=company_name,
        status=SourceStatus.REVIEWED,
        careers_url=f"https://jobs.ashbyhq.com/{company_id}",
        adapter_type=AdapterType.ASHBY,
        adapter_parameters={"board_name": company_id},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            field_name="publishedAt",
            basis=DateBasis.PUBLISHED,
            verified_as_publication=True,
            notes="",
        ),
        detail_strategy=DetailStrategy.LISTING_PAYLOAD,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(f"https://jobs.ashbyhq.com/{company_id}",),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def registry() -> CompanySourceRegistry:
    return CompanySourceRegistry(
        schema_version=1,
        registry_version="test-registry",
        generated_at=datetime(2026, 9, 20, tzinfo=UTC),
        discovery_batch_id="test",
        entries=(
            CompanyRegistryEntry(2, "P1", None, source("two", "Two")),
            CompanyRegistryEntry(1, "P1", None, source("one", "One")),
        ),
    )


def job(company_source: CompanySource) -> NormalizedJob:
    return NormalizedJob(
        schema_version=1,
        company_id=company_source.company_id,
        source_type="ashby",
        external_job_id=f"{company_source.company_id}-job",
        title_original="Machine Learning Engineer",
        title_normalized="machine learning engineer",
        location_original="Bengaluru, India",
        location_normalized=("bengaluru", "india"),
        published_at=datetime(2026, 9, 19, tzinfo=UTC),
        published_at_raw="2026-09-19T00:00:00Z",
        date_basis=DateBasis.PUBLISHED,
        canonical_url=f"https://jobs.ashbyhq.com/{company_source.company_id}/job",
    )


@dataclass(frozen=True)
class StubAshbyAdapter:
    adapter_type: AdapterType = AdapterType.ASHBY

    def list_jobs(self, company_source: CompanySource) -> AdapterResult:
        return AdapterResult(
            schema_version=1,
            source=company_source,
            outcome=AdapterOutcome.SUCCESS,
            jobs=(job(company_source),),
            page_count=1,
            complete=True,
            diagnostics=(),
        )


def test_verification_orders_companies_and_reports_required_health_fields() -> None:
    report = verify_adapter_sources(
        registry(),
        AdapterRegistry([StubAshbyAdapter()]),
        AdapterType.ASHBY,
        generated_at=datetime(2026, 9, 20, 10, tzinfo=UTC),
    )

    assert report.healthy is True
    assert report.schema_version == 2
    assert report.outcome_counts == {"success": 2}
    assert report.failure_category_counts == {}
    assert report.anomaly_counts == {}
    assert [record.company_id for record in report.records] == ["one", "two"]
    assert report.records[0].configuration_version == "test-registry"
    assert report.records[0].job_count == 1
    assert report.records[0].page_count == 1
    assert report.records[0].missing_field_count == 0
    assert report.records[0].date_basis_distribution["published"] == 1
    assert report.records[0].attempt_count == 1
    assert report.records[0].failure_categories == ()
    assert report.records[0].anomaly_categories == ()
    assert report.records[0].sample_job_urls == ("https://jobs.ashbyhq.com/one/job",)


def test_company_selection_rejects_wrong_family_or_duplicate_ids() -> None:
    adapters = AdapterRegistry([StubAshbyAdapter()])

    with pytest.raises(ValueError, match="not configured"):
        verify_adapter_sources(registry(), adapters, AdapterType.ASHBY, company_ids=("missing",))
    with pytest.raises(ValueError, match="duplicates"):
        verify_adapter_sources(registry(), adapters, AdapterType.ASHBY, company_ids=("one", "one"))


def test_report_writer_excludes_job_descriptions(tmp_path: Path) -> None:
    report = verify_adapter_sources(
        registry(),
        AdapterRegistry([StubAshbyAdapter()]),
        AdapterType.ASHBY,
        generated_at=datetime(2026, 9, 20, 10, tzinfo=UTC),
    )
    output = tmp_path / "verification.json"

    write_verification_report(report, output)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["company_count"] == 2
    assert "description" not in output.read_text(encoding="utf-8")


def test_enabled_verification_selects_only_enabled_sources_in_registry_order() -> None:
    base = registry()
    enabled_source = replace(
        base.entries[0].source,
        status=SourceStatus.ENABLED,
        enabled=True,
    )
    mixed = CompanySourceRegistry(
        schema_version=base.schema_version,
        registry_version=base.registry_version,
        generated_at=base.generated_at,
        discovery_batch_id=base.discovery_batch_id,
        entries=(
            replace(base.entries[0], source=enabled_source),
            base.entries[1],
        ),
    )

    report = verify_enabled_sources(
        mixed,
        AdapterRegistry([StubAshbyAdapter()]),
        generated_at=datetime(2026, 9, 20, 10, tzinfo=UTC),
    )

    assert report.adapter_type == "all_enabled"
    assert report.company_count == 1
    assert report.outcome_counts == {"success": 1}
    assert [record.company_id for record in report.records] == ["two"]


@dataclass(frozen=True)
class EmptyAshbyAdapter:
    adapter_type: AdapterType = AdapterType.ASHBY

    def list_jobs(self, company_source: CompanySource) -> AdapterResult:
        return AdapterResult(1, company_source, AdapterOutcome.EMPTY, (), 1, True, ())


@dataclass(frozen=True)
class DiagnosticAshbyAdapter:
    diagnostic: AdapterDiagnostic
    outcome: AdapterOutcome = AdapterOutcome.FAILED
    adapter_type: AdapterType = AdapterType.ASHBY

    def list_jobs(self, company_source: CompanySource) -> AdapterResult:
        return AdapterResult(
            1,
            company_source,
            self.outcome,
            (),
            0,
            False,
            (self.diagnostic,),
        )


def test_historical_count_collapse_is_suspicious_not_healthy_empty() -> None:
    report = verify_adapter_sources(
        registry(),
        AdapterRegistry([EmptyAshbyAdapter()]),
        AdapterType.ASHBY,
        baseline=VerificationBaseline(
            generated_at="2026-09-19T10:00:00+00:00",
            job_counts={"one": 100, "two": 5},
        ),
        generated_at=datetime(2026, 9, 20, 10, tzinfo=UTC),
    )

    assert report.healthy is False
    assert report.outcome_counts == {"empty": 1, "suspicious": 1}
    assert report.anomaly_counts == {SourceAnomaly.RESULT_COUNT_COLLAPSE.value: 1}
    collapsed = next(record for record in report.records if record.company_id == "one")
    assert collapsed.complete is False
    assert collapsed.failure_categories == (FailureCategory.SCHEMA_CHANGE.value,)
    assert collapsed.exception_categories == (SourceAnomaly.RESULT_COUNT_COLLAPSE.value,)


@pytest.mark.parametrize(
    ("diagnostic", "expected"),
    [
        (
            AdapterDiagnostic(
                "timeout",
                DiagnosticSeverity.ERROR,
                "request timed out",
                {"retryable": "true"},
            ),
            FailureCategory.TEMPORARY_AVAILABILITY,
        ),
        (
            AdapterDiagnostic(
                "http_error",
                DiagnosticSeverity.ERROR,
                "HTTP 429",
                {"retryable": "true", "status_code": "429"},
            ),
            FailureCategory.RATE_LIMIT,
        ),
        (
            AdapterDiagnostic(
                "http_error",
                DiagnosticSeverity.ERROR,
                "HTTP 404",
                {"retryable": "false", "status_code": "404"},
            ),
            FailureCategory.SOURCE_MOVED,
        ),
        (
            AdapterDiagnostic(
                "access_block",
                DiagnosticSeverity.ERROR,
                "access-control page detected",
                {},
            ),
            FailureCategory.ACCESS_RESTRICTION,
        ),
        (
            AdapterDiagnostic(
                "unsupported_schema",
                DiagnosticSeverity.ERROR,
                "required field is missing",
                {},
            ),
            FailureCategory.SCHEMA_CHANGE,
        ),
        (
            AdapterDiagnostic(
                "repeated_page",
                DiagnosticSeverity.ERROR,
                "pagination repeated",
                {},
            ),
            FailureCategory.PARSER_DEFECT,
        ),
    ],
)
def test_adapter_diagnostics_map_to_stable_failure_categories(
    diagnostic: AdapterDiagnostic,
    expected: FailureCategory,
) -> None:
    report = verify_adapter_sources(
        registry(),
        AdapterRegistry([DiagnosticAshbyAdapter(diagnostic)]),
        AdapterType.ASHBY,
        generated_at=datetime(2026, 9, 20, 10, tzinfo=UTC),
    )

    assert report.healthy is False
    assert report.failure_category_counts == {expected.value: 2}
    assert all(record.failure_categories == (expected.value,) for record in report.records)


def test_missing_adapter_is_contained_as_configuration_error() -> None:
    report = verify_adapter_sources(
        registry(),
        AdapterRegistry(),
        AdapterType.ASHBY,
        generated_at=datetime(2026, 9, 20, 10, tzinfo=UTC),
    )

    assert report.outcome_counts == {"failed": 2}
    assert report.failure_category_counts == {
        FailureCategory.CONFIGURATION_ERROR.value: 2,
    }
    assert all(record.exception_categories == ("configuration_error",) for record in report.records)


def test_future_and_uniformly_stale_publication_dates_are_suspicious() -> None:
    base = registry()
    now = datetime(2026, 9, 20, 10, tzinfo=UTC)

    @dataclass(frozen=True)
    class DatedAdapter:
        adapter_type: AdapterType = AdapterType.ASHBY

        def list_jobs(self, company_source: CompanySource) -> AdapterResult:
            if company_source.company_id == "one":
                jobs = (replace(job(company_source), published_at=now + timedelta(days=2)),)
            else:
                jobs = tuple(
                    replace(
                        job(company_source),
                        external_job_id=f"stale-{index}",
                        canonical_url=f"https://jobs.ashbyhq.com/two/stale-{index}",
                        published_at=now - timedelta(days=500 + index),
                    )
                    for index in range(5)
                )
            return AdapterResult(1, company_source, AdapterOutcome.SUCCESS, jobs, 1, True, ())

    report = verify_adapter_sources(
        base,
        AdapterRegistry([DatedAdapter()]),
        AdapterType.ASHBY,
        generated_at=now,
    )

    assert report.outcome_counts == {"suspicious": 2}
    assert report.anomaly_counts == {
        SourceAnomaly.FUTURE_PUBLICATION_DATE.value: 1,
        SourceAnomaly.STALE_PUBLICATION_DATES.value: 1,
    }


def test_baseline_loader_keeps_only_valid_unique_counts(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-09-19T10:00:00+00:00",
                "records": [
                    {"company_id": "one", "job_count": 25, "ignored": "value"},
                    {"company_id": "two", "job_count": 0},
                ],
            }
        ),
        encoding="utf-8",
    )

    baseline = load_verification_baseline(path)

    assert baseline.generated_at == "2026-09-19T10:00:00+00:00"
    assert baseline.job_counts == {"one": 25, "two": 0}
