"""Tests for full-registry recency measurement and sanitized reporting."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

import job_finder.recency_verification as recency_verification
from job_finder.adapters.base import AdapterRegistry
from job_finder.core.company_registry import CompanyRegistryEntry, CompanySourceRegistry
from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.core.recency import CompanyDateCoverageClass
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
from job_finder.recency_verification import measure_enabled_recency, write_recency_report

SCAN_AT = datetime(2026, 9, 20, 12, tzinfo=UTC)


def source(company_id: str) -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id=company_id,
        company_name=company_id.title(),
        status=SourceStatus.ENABLED,
        careers_url=f"https://jobs.example.com/{company_id}",
        adapter_type=AdapterType.ASHBY,
        adapter_parameters={"board_name": company_id},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            field_name="publishedAt",
            basis=DateBasis.PUBLISHED,
            verified_as_publication=True,
            notes="test",
        ),
        detail_strategy=DetailStrategy.LISTING_PAYLOAD,
        enabled=True,
        confidence=Confidence.HIGH,
        evidence=(f"https://jobs.example.com/{company_id}",),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def job(
    company_id: str,
    suffix: str,
    *,
    value: datetime | date | None,
    raw: str | None,
    basis: DateBasis = DateBasis.PUBLISHED,
) -> NormalizedJob:
    return NormalizedJob(
        schema_version=1,
        company_id=company_id,
        source_type="ashby",
        external_job_id=suffix,
        title_original="ML Engineer",
        title_normalized="ml engineer",
        location_original="Bangalore, India",
        location_normalized=("bangalore, india",),
        published_at=value,
        published_at_raw=raw,
        date_basis=basis,
        canonical_url=f"https://jobs.example.com/{company_id}?jobId={suffix}&utm_source=test",
        description="must never be written",
    )


@dataclass(frozen=True)
class StubAdapter:
    adapter_type: AdapterType = AdapterType.ASHBY

    def list_jobs(self, company_source: CompanySource) -> AdapterResult:
        if company_source.company_id == "empty":
            return AdapterResult(1, company_source, AdapterOutcome.EMPTY, (), 1, True, ())
        if company_source.company_id == "failed":
            diagnostic = AdapterDiagnostic(
                category="request_failed",
                severity=DiagnosticSeverity.ERROR,
                message="test failure",
                context={},
            )
            return AdapterResult(
                1,
                company_source,
                AdapterOutcome.FAILED,
                (),
                0,
                False,
                (diagnostic,),
            )
        jobs = (
            job(
                "mixed",
                "inside",
                value=SCAN_AT - timedelta(days=1),
                raw="2026-09-19T12:00:00Z",
            ),
            job(
                "mixed",
                "outside",
                value=SCAN_AT - timedelta(days=11),
                raw="2026-09-09T12:00:00Z",
            ),
            job("mixed", "invalid", value=None, raw="not-a-date"),
            job(
                "mixed",
                "uncertain",
                value=None,
                raw="Posted 2 Days Ago",
                basis=DateBasis.UNKNOWN,
            ),
            job("mixed", "missing", value=None, raw=None),
        )
        return AdapterResult(1, company_source, AdapterOutcome.SUCCESS, jobs, 1, True, ())


@dataclass(frozen=True)
class CompletionBoundaryAdapter:
    clock_calls: list[datetime]
    adapter_type: AdapterType = AdapterType.ASHBY

    def list_jobs(self, company_source: CompanySource) -> AdapterResult:
        assert self.clock_calls == []
        jobs = (
            job(
                company_source.company_id,
                "during-scan",
                value=SCAN_AT - timedelta(minutes=1),
                raw="2026-09-20T11:59:00Z",
            ),
        )
        return AdapterResult(1, company_source, AdapterOutcome.SUCCESS, jobs, 1, True, ())


@dataclass
class RetryOnceAdapter:
    call_count: int = 0
    adapter_type: AdapterType = AdapterType.ASHBY

    def list_jobs(self, company_source: CompanySource) -> AdapterResult:
        self.call_count += 1
        if self.call_count == 1:
            diagnostic = AdapterDiagnostic(
                category="invalid_json",
                severity=DiagnosticSeverity.ERROR,
                message="transient invalid response",
                context={},
            )
            return AdapterResult(
                1,
                company_source,
                AdapterOutcome.FAILED,
                (),
                1,
                False,
                (diagnostic,),
            )
        jobs = (
            job(
                company_source.company_id,
                "recovered",
                value=SCAN_AT - timedelta(days=1),
                raw="2026-09-19T12:00:00Z",
            ),
        )
        return AdapterResult(1, company_source, AdapterOutcome.SUCCESS, jobs, 1, True, ())


def registry() -> CompanySourceRegistry:
    return CompanySourceRegistry(
        schema_version=1,
        registry_version="test",
        generated_at=SCAN_AT,
        discovery_batch_id="test",
        entries=tuple(
            CompanyRegistryEntry(index, "P1", None, source(company_id))
            for index, company_id in enumerate(("mixed", "empty", "failed"), start=1)
        ),
    )


def test_measurement_reports_company_adapter_listing_and_decision_counts() -> None:
    report = measure_enabled_recency(
        registry(),
        AdapterRegistry([StubAdapter()]),
        load_search_profile(Path("config/search_profile.toml")),
        scan_at=SCAN_AT,
    )

    assert report.healthy is False
    assert report.enabled_company_count == 3
    assert report.outcome_counts == {"empty": 1, "failed": 1, "success": 1}
    assert report.company_class_counts == {
        CompanyDateCoverageClass.ALL_RELIABLE: 0,
        CompanyDateCoverageClass.MIXED: 1,
        CompanyDateCoverageClass.NO_RELIABLE: 0,
        CompanyDateCoverageClass.NO_LISTINGS: 1,
        CompanyDateCoverageClass.UNASSESSED: 1,
    }
    assert report.listing_count == 5
    assert report.valid_identity_count == 5
    assert report.valid_url_count == 5
    assert asdict(report.listing_counts) == {
        "reliable": 2,
        "uncertain": 1,
        "invalid": 1,
        "missing": 1,
    }
    assert asdict(report.decision_counts) == {
        "inside_window": 1,
        "outside_window": 1,
        "uncertain": 2,
        "invalid": 1,
    }
    assert report.first_seen_available_count == 0
    assert report.by_adapter["ashby"].listing_count == 5


def test_report_writer_retains_public_evidence_without_descriptions(tmp_path: Path) -> None:
    report = measure_enabled_recency(
        registry(),
        AdapterRegistry([StubAdapter()]),
        load_search_profile(Path("config/search_profile.toml")),
        scan_at=SCAN_AT,
    )
    output = tmp_path / "recency.json"

    write_recency_report(report, output)
    text = output.read_text(encoding="utf-8")
    payload = json.loads(text)

    assert "must never be written" not in text
    assert payload["companies"][0]["observations"][0]["job_url"].endswith("?jobId=inside")
    assert payload["companies"][0]["observations"][2]["raw_date_text"] == "not-a-date"
    assert payload["companies"][0]["observations"][2]["evidence_status"] == "invalid"


def test_default_scan_boundary_is_captured_after_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock_calls: list[datetime] = []

    def completed_at() -> datetime:
        clock_calls.append(SCAN_AT)
        return SCAN_AT

    monkeypatch.setattr(recency_verification, "_local_now", completed_at)
    company_source = source("during-scan")
    single_registry = CompanySourceRegistry(
        schema_version=1,
        registry_version="test",
        generated_at=SCAN_AT,
        discovery_batch_id="test",
        entries=(CompanyRegistryEntry(1, "P1", None, company_source),),
    )

    report = measure_enabled_recency(
        single_registry,
        AdapterRegistry([CompletionBoundaryAdapter(clock_calls)]),
        load_search_profile(Path("config/search_profile.toml")),
    )

    assert clock_calls == [SCAN_AT]
    assert report.scan_at == SCAN_AT.isoformat(timespec="seconds")
    assert report.decision_counts.inside_window == 1
    assert report.decision_counts.invalid == 0


def test_measurement_retries_a_transient_incomplete_source_scan() -> None:
    company_source = source("transient")
    single_registry = CompanySourceRegistry(
        schema_version=1,
        registry_version="test",
        generated_at=SCAN_AT,
        discovery_batch_id="test",
        entries=(CompanyRegistryEntry(1, "P1", None, company_source),),
    )
    adapter = RetryOnceAdapter()

    report = measure_enabled_recency(
        single_registry,
        AdapterRegistry([adapter]),
        load_search_profile(Path("config/search_profile.toml")),
        scan_at=SCAN_AT,
    )

    assert adapter.call_count == 2
    assert report.healthy is True
    assert report.companies[0].attempt_count == 2
    assert report.companies[0].exception_categories == ("source_retry_succeeded",)
