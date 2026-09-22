"""Tests for stable job identity priority and fallback behavior."""

from __future__ import annotations

from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.persistence.identity import (
    JobIdentityStrategy,
    build_fallback_fingerprint,
    job_identity,
)


def make_job(
    *,
    external_job_id: str | None = "REQ-42",
    canonical_url: str = "https://jobs.example.com/opening/42",
    title: str = "Senior ML Engineer",
    locations: tuple[str, ...] = ("bengaluru india",),
    source_type: str = "example",
) -> NormalizedJob:
    return NormalizedJob(
        schema_version=1,
        company_id="example-company",
        source_type=source_type,
        external_job_id=external_job_id,
        title_original=title,
        title_normalized=title,
        location_original=" | ".join(locations),
        location_normalized=locations,
        published_at=None,
        published_at_raw=None,
        date_basis=DateBasis.UNKNOWN,
        canonical_url=canonical_url,
    )


def test_external_id_takes_priority_over_url_and_fallback_fields() -> None:
    first = job_identity(make_job())
    second = job_identity(
        make_job(
            canonical_url="https://jobs.example.com/new-path/42",
            title="Machine Learning Engineer",
            locations=("hyderabad india",),
        )
    )

    assert first.strategy is JobIdentityStrategy.EXTERNAL_ID
    assert first.job_key == second.job_key
    assert first.fallback_fingerprint != second.fallback_fingerprint


def test_separate_external_ids_remain_separate() -> None:
    first = job_identity(make_job(external_job_id="REQ-42"))
    second = job_identity(make_job(external_job_id="REQ-43"))

    assert first.job_key != second.job_key


def test_source_type_scopes_external_ids() -> None:
    first = job_identity(make_job(source_type="greenhouse"))
    second = job_identity(make_job(source_type="workday"))

    assert first.job_key != second.job_key


def test_tracking_parameter_changes_do_not_change_url_identity() -> None:
    first = job_identity(
        make_job(
            external_job_id=None,
            canonical_url="https://jobs.example.com/opening/42?jobId=42&utm_source=mail",
        )
    )
    second = job_identity(
        make_job(
            external_job_id=None,
            canonical_url="https://JOBS.example.com/opening/42?jobId=42&source=linkedin#apply",
        )
    )

    assert first.strategy is JobIdentityStrategy.CANONICAL_URL
    assert first.job_key == second.job_key
    assert first.canonical_url == "https://jobs.example.com/opening/42?jobId=42"


def test_fallback_identity_is_stable_under_whitespace_and_location_order() -> None:
    first = build_fallback_fingerprint(
        company_id="example-company",
        title="Senior  ML Engineer",
        locations=("bengaluru india", "hyderabad india"),
        team="AI Platform",
    )
    second = build_fallback_fingerprint(
        company_id="example-company",
        title=" Senior ML Engineer ",
        locations=("  Hyderabad India ", "Bengaluru India"),
        team=" AI  Platform ",
    )

    assert first == second


def test_fallback_identity_keeps_departments_separate() -> None:
    first = build_fallback_fingerprint(
        company_id="example-company",
        title="ML Engineer",
        locations=("bengaluru",),
        department="Search",
    )
    second = build_fallback_fingerprint(
        company_id="example-company",
        title="ML Engineer",
        locations=("bengaluru",),
        department="Ads",
    )

    assert first != second
