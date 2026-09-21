"""Tests for complete-registry role and location reduction reporting."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from job_finder.adapters.base import AdapterRegistry
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
from job_finder.filter_verification import (
    FinalFilterDecision,
    verify_filters,
    write_filter_report,
    write_filter_review,
)

SCAN_AT = datetime(2026, 9, 22, 12, tzinfo=UTC)


def source() -> CompanySource:
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
        DetailStrategy.LISTING_PAYLOAD,
        True,
        Confidence.HIGH,
        ("https://jobs.example.com",),
        False,
        None,
        "",
    )


def job(identifier: str, title: str, location: str, *, days_old: int = 1) -> NormalizedJob:
    return NormalizedJob(
        1,
        "example",
        "ashby",
        identifier,
        title,
        title.casefold(),
        location,
        (location.casefold(),),
        SCAN_AT - timedelta(days=days_old),
        (SCAN_AT - timedelta(days=days_old)).isoformat(),
        DateBasis.PUBLISHED,
        f"https://jobs.example.com/{identifier}",
        "secret description must not be written",
    )


@dataclass(frozen=True)
class StubAdapter:
    adapter_type: AdapterType = AdapterType.ASHBY

    def list_jobs(self, company_source: CompanySource) -> AdapterResult:
        jobs = (
            job("keep", "Machine Learning Engineer", "Bengaluru, India"),
            job("conditional", "Software Engineer", "India"),
            job("role-reject", "Product Manager, AI", "India"),
            job("location-review", "AI Engineer", "Remote"),
            job("old", "ML Engineer", "India", days_old=11),
        )
        return AdapterResult(1, company_source, AdapterOutcome.SUCCESS, jobs, 1, True, ())


def registry() -> CompanySourceRegistry:
    return CompanySourceRegistry(
        1,
        "test",
        SCAN_AT,
        "test",
        (CompanyRegistryEntry(1, "P1", None, source()),),
    )


def test_filter_report_reconciles_every_reduction_stage() -> None:
    report = verify_filters(
        registry(),
        AdapterRegistry([StubAdapter()]),
        load_search_profile(Path("config/search_profile.toml")),
        scan_at=SCAN_AT,
    )

    assert report.healthy is True
    assert report.listing_count == 5
    assert report.strict_recent_count == 4
    assert report.recency_excluded_count == 1
    assert report.role_counts == {
        "conditional_description": 1,
        "explicit_pass": 2,
        "reject": 1,
    }
    assert report.location_counts == {"pass": 2, "review": 1}
    assert report.final_counts == {"rejected": 1, "retained": 2, "review": 1}
    assert report.companies[0].retained_count == 2
    assert {row.final_decision for row in report.listings} == {
        FinalFilterDecision.RETAINED,
        FinalFilterDecision.REJECTED,
        FinalFilterDecision.REVIEW,
    }


def test_filter_outputs_are_sanitized_and_human_readable(tmp_path: Path) -> None:
    report = verify_filters(
        registry(),
        AdapterRegistry([StubAdapter()]),
        load_search_profile(Path("config/search_profile.toml")),
        scan_at=SCAN_AT,
    )
    json_path = tmp_path / "filter.json"
    review_path = tmp_path / "review.md"

    write_filter_report(report, json_path)
    write_filter_review(report, review_path)
    json_text = json_path.read_text(encoding="utf-8")
    review_text = review_path.read_text(encoding="utf-8")

    assert "secret description" not in json_text
    assert json.loads(json_text)["final_counts"]["retained"] == 2
    assert "Machine Learning Engineer" in review_text
    assert "Product Manager" in review_text
    assert "Remote" in review_text
