"""Tests for read-only source-verification reporting."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterRegistry
from job_finder.core.company_registry import CompanyRegistryEntry, CompanySourceRegistry
from job_finder.core.job_contracts import DateBasis, NormalizedJob
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
from job_finder.verification import (
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
    assert report.outcome_counts == {"success": 2}
    assert [record.company_id for record in report.records] == ["one", "two"]
    assert report.records[0].configuration_version == "test-registry"
    assert report.records[0].job_count == 1
    assert report.records[0].page_count == 1
    assert report.records[0].missing_field_count == 0
    assert report.records[0].date_basis_distribution["published"] == 1
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
