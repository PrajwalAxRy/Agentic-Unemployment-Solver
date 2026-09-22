"""Tests for two-pass filtered-candidate persistence validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
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
from job_finder.persistence_verification import second_pass_new_companies, verify_persistence


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
        DetailStrategy.LISTING_PAYLOAD,
        True,
        Confidence.HIGH,
        ("https://jobs.example.com",),
        False,
        None,
        "",
    )


def _job(identifier: str) -> NormalizedJob:
    published = datetime.now(UTC)
    return NormalizedJob(
        1,
        "example",
        "ashby",
        identifier,
        "Machine Learning Engineer",
        "machine learning engineer",
        "Bengaluru, India",
        ("bengaluru india",),
        published,
        published.isoformat(),
        DateBasis.PUBLISHED,
        f"https://jobs.example.com/{identifier}?utm_source=test",
    )


def _registry() -> CompanySourceRegistry:
    return CompanySourceRegistry(
        1,
        "test-registry",
        datetime.now(UTC),
        "test",
        (CompanyRegistryEntry(1, "P1", None, _source()),),
    )


@dataclass
class StableAdapter:
    adapter_type: AdapterType = AdapterType.ASHBY

    def list_jobs(self, company_source: CompanySource) -> AdapterResult:
        return AdapterResult(
            1,
            company_source,
            AdapterOutcome.SUCCESS,
            (_job("one"), _job("two")),
            1,
            True,
            (),
        )


@dataclass
class ChangingAdapter:
    adapter_type: AdapterType = AdapterType.ASHBY
    call_count: int = 0

    def list_jobs(self, company_source: CompanySource) -> AdapterResult:
        self.call_count += 1
        identifiers = ("one",) if self.call_count == 1 else ("one", "new-on-second-pass")
        return AdapterResult(
            1,
            company_source,
            AdapterOutcome.SUCCESS,
            tuple(_job(identifier) for identifier in identifiers),
            1,
            True,
            (),
        )


def test_unchanged_second_pass_produces_zero_new_identities(tmp_path: Path) -> None:
    report = verify_persistence(
        _registry(),
        AdapterRegistry([StableAdapter()]),
        load_search_profile(Path("config/search_profile.toml")),
        database_path=tmp_path / "state" / "jobs.sqlite3",
        lock_path=tmp_path / "state" / "scan.lock",
    )

    assert report.healthy is True
    assert report.initial_identity_count == 0
    assert report.final_identity_count == 2
    assert report.expected_pass_count == 2
    assert report.passes[0].new_identity_count == 2
    assert report.passes[1].new_identity_count == 0
    assert report.passes[1].existing_identity_count == 2
    assert report.passes[1].source_outcomes == {"success": 1}
    assert report.passes[1].source_issues == ()
    assert second_pass_new_companies(report) == {}


def test_second_pass_inventory_change_remains_visible_for_investigation(tmp_path: Path) -> None:
    report = verify_persistence(
        _registry(),
        AdapterRegistry([ChangingAdapter()]),
        load_search_profile(Path("config/search_profile.toml")),
        database_path=tmp_path / "jobs.sqlite3",
        lock_path=tmp_path / "scan.lock",
    )

    assert report.healthy is False
    assert report.passes[1].new_identity_count == 1
    assert report.passes[1].new_identities[0].title == "Machine Learning Engineer"
    assert second_pass_new_companies(report) == {"example": 1}


def test_existing_validation_state_can_run_one_clean_continuation_pass(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"
    lock = tmp_path / "scan.lock"
    profile = load_search_profile(Path("config/search_profile.toml"))
    first = verify_persistence(
        _registry(),
        AdapterRegistry([StableAdapter()]),
        profile,
        database_path=database,
        lock_path=lock,
    )

    continuation = verify_persistence(
        _registry(),
        AdapterRegistry([StableAdapter()]),
        profile,
        database_path=database,
        lock_path=lock,
        require_empty=False,
        pass_count=1,
    )

    assert first.final_identity_count == 2
    assert continuation.healthy is True
    assert continuation.initial_identity_count == 2
    assert continuation.final_identity_count == 2
    assert continuation.passes[0].new_identity_count == 0
