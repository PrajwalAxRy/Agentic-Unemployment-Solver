"""Tests for complete-registry role and location reduction reporting."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from job_finder.adapters.base import AdapterRegistry
from job_finder.collection import (
    FinalFilterDecision,
    collect_listings,
    write_filter_report,
    write_filter_review,
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

SCAN_AT = datetime(2026, 9, 22, 12, tzinfo=UTC)


def source(adapter_type: AdapterType = AdapterType.ASHBY) -> CompanySource:
    return CompanySource(
        1,
        "example",
        "Example",
        SourceStatus.ENABLED,
        "https://jobs.example.com",
        adapter_type,
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


@dataclass(frozen=True)
class WorkdayDetailStub:
    adapter_type: AdapterType = AdapterType.WORKDAY

    def list_jobs(self, company_source: CompanySource) -> AdapterResult:
        listing = replace(
            job("multi", "AI Engineer", "2 Locations"),
            source_type="workday",
            location_normalized=("2 locations",),
            source_metadata={"external_path": "/job/multi"},
        )
        return AdapterResult(1, company_source, AdapterOutcome.SUCCESS, (listing,), 1, True, ())

    def get_job_detail(
        self, company_source: CompanySource, listing: NormalizedJob
    ) -> NormalizedJob:
        return replace(
            listing,
            location_original="Bengaluru, India | London, UK",
            location_normalized=("bengaluru india", "london uk"),
        )


@dataclass(frozen=True)
class JobviteDetailStub:
    adapter_type: AdapterType = AdapterType.JOBVITE

    def list_jobs(self, company_source: CompanySource) -> AdapterResult:
        listing = replace(
            job("old-detail", "AI Engineer", "Bengaluru, India"),
            source_type="jobvite",
            published_at=None,
            published_at_raw=None,
            date_basis=DateBasis.UNKNOWN,
        )
        return AdapterResult(1, company_source, AdapterOutcome.SUCCESS, (listing,), 1, True, ())

    def get_job_detail(
        self, company_source: CompanySource, listing: NormalizedJob
    ) -> NormalizedJob:
        published = SCAN_AT - timedelta(days=11)
        return replace(
            listing,
            published_at=published,
            published_at_raw=published.isoformat(),
            date_basis=DateBasis.PUBLISHED,
        )


@dataclass(frozen=True)
class UncertainDateStub:
    adapter_type: AdapterType = AdapterType.ASHBY

    def list_jobs(self, company_source: CompanySource) -> AdapterResult:
        listing = replace(
            job("uncertain", "AI Engineer", "Bengaluru, India"),
            published_at=None,
            published_at_raw="2 days ago",
            date_basis=DateBasis.UNKNOWN,
        )
        return AdapterResult(1, company_source, AdapterOutcome.SUCCESS, (listing,), 1, True, ())


def test_filter_report_reconciles_every_reduction_stage() -> None:
    report = collect_listings(
        registry(),
        AdapterRegistry([StubAdapter()]),
        load_search_profile(Path("config/search_profile.toml")),
        scan_at=SCAN_AT,
    )

    assert report.healthy is True
    assert report.listing_count == 5
    assert report.strict_recent_count == 4
    assert report.recency_excluded_count == 1
    # 2.2: no title may grant a pass or skip the relevance gate, so explicit_pass is no
    # longer reachable from a title. Every surviving title is conditional and the LLM
    # decides domain from the description. final_counts is unchanged.
    assert report.role_counts == {
        "conditional_description": 3,
        "reject": 1,
    }
    # Location now runs before title (to_change.md 2.1), so every recency-eligible row
    # gets a location decision -- including "Product Manager, AI", whose location was
    # previously never evaluated because the title filter rejected it first. The extra
    # "pass" is improved reporting, not a behaviour change: final_counts is unchanged.
    assert report.location_counts == {"pass": 3, "review": 1}
    assert report.final_counts == {"rejected": 1, "retained": 2, "review": 1}
    assert report.companies[0].retained_count == 2
    assert {row.final_decision for row in report.listings} == {
        FinalFilterDecision.RETAINED,
        FinalFilterDecision.REJECTED,
        FinalFilterDecision.REVIEW,
    }


def test_filter_outputs_are_sanitized_and_human_readable(tmp_path: Path) -> None:
    report = collect_listings(
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
    assert "Role family/lane" in review_text
    assert "| K01 |" in review_text
    assert "| X01 |" in review_text
    assert "| L01 |" in review_text
    assert "| R01 |" not in review_text
    assert "role_rejected" in review_text


def test_workday_multi_location_is_resolved_before_location_filtering() -> None:
    company_source = source(AdapterType.WORKDAY)
    report = collect_listings(
        CompanySourceRegistry(
            1,
            "test",
            SCAN_AT,
            "test",
            (CompanyRegistryEntry(1, "P1", None, company_source),),
        ),
        AdapterRegistry([WorkdayDetailStub()]),
        load_search_profile(Path("config/search_profile.toml")),
        scan_at=SCAN_AT,
    )

    assert report.final_counts == {"retained": 1}
    assert report.detail_fetch_count == 1
    assert report.detail_failure_count == 0


def test_jobvite_detail_date_is_applied_after_role_and_location_pass() -> None:
    company_source = replace(
        source(AdapterType.JOBVITE),
        date_strategy=DateStrategy("datePosted", DateBasis.PUBLISHED, True, "test"),
    )
    report = collect_listings(
        CompanySourceRegistry(
            1,
            "test",
            SCAN_AT,
            "test",
            (CompanyRegistryEntry(1, "P1", None, company_source),),
        ),
        AdapterRegistry([JobviteDetailStub()]),
        load_search_profile(Path("config/search_profile.toml")),
        scan_at=SCAN_AT,
    )

    assert report.final_counts == {}
    assert report.recency_excluded_count == 1
    assert report.detail_fetch_count == 1


def test_uncertain_date_uses_first_seen_only_for_forward_aging() -> None:
    company_source = replace(
        source(),
        date_strategy=DateStrategy("relative", DateBasis.UNKNOWN, False, "test"),
    )
    test_registry = CompanySourceRegistry(
        1,
        "test",
        SCAN_AT,
        "test",
        (CompanyRegistryEntry(1, "P1", None, company_source),),
    )
    recent = collect_listings(
        test_registry,
        AdapterRegistry([UncertainDateStub()]),
        load_search_profile(Path("config/search_profile.toml")),
        scan_at=SCAN_AT,
        first_seen_lookup=lambda _: SCAN_AT - timedelta(days=2),
    )
    old = collect_listings(
        test_registry,
        AdapterRegistry([UncertainDateStub()]),
        load_search_profile(Path("config/search_profile.toml")),
        scan_at=SCAN_AT,
        first_seen_lookup=lambda _: SCAN_AT - timedelta(days=11),
    )

    assert recent.uncertain_candidate_count == 1
    assert recent.strict_recent_count == 0
    assert recent.final_counts == {"retained": 1}
    assert old.uncertain_candidate_count == 0
    assert old.recency_excluded_count == 1


def test_source_timing_is_reported() -> None:
    """Per-company timing, with median alongside mean.

    The distribution is long-tailed -- one Workday board with 553 jobs across 28 paginated
    requests takes minutes while most companies take under a second. A mean over that mix
    describes no actual company, which is why median and max are reported too, and why
    `slowest` names the specific companies you can act on.
    """
    report = collect_listings(
        registry(),
        AdapterRegistry([StubAdapter()]),
        load_search_profile(Path("config/search_profile.toml")),
        scan_at=SCAN_AT,
    )

    timing = report.timing
    assert timing is not None
    assert timing["company_count"] == report.enabled_company_count
    for key in ("total_seconds", "mean_seconds", "median_seconds", "min_seconds", "max_seconds"):
        assert isinstance(timing[key], (int, float)), key
        assert timing[key] >= 0, key
    assert timing["min_seconds"] <= timing["median_seconds"] <= timing["max_seconds"]
    assert timing["slowest"], "the slowest companies must be named, not just counted"
    assert {"company_id", "adapter_type", "seconds", "listings"} <= set(timing["slowest"][0])
    # Per-company durations are on the company records too, for the JSON report.
    assert all(company.duration_seconds >= 0 for company in report.companies)
