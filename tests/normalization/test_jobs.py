"""Tests for source-independent job normalization."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.core.search_profile import load_search_profile
from job_finder.normalization.jobs import (
    canonicalize_job_url,
    normalize_job,
    normalize_location_values,
    normalize_title,
    parse_source_timestamp,
)


def test_title_normalization_collapses_unicode_punctuation_and_whitespace() -> None:
    assert normalize_title("  Senior\u00a0Machine–Learning / AI Engineer  ") == (
        "senior machine learning ai engineer"
    )


def test_location_normalization_supports_aliases_and_multiple_locations() -> None:
    policy = load_search_profile(Path("config/search_profile.toml")).location

    assert normalize_location_values(
        "Bangalore, Karnataka, India | Gurgaon, Haryana, IN",
        policy=policy,
    ) == (
        "bengaluru karnataka india",
        "gurugram haryana in",
    )


def test_canonical_url_removes_tracking_but_preserves_identity_parameters() -> None:
    assert (
        canonicalize_job_url(
            "HTTPS://Jobs.Example.com/opening?utm_source=mail&jobId=42&source=linkedin#apply"
        )
        == "https://jobs.example.com/opening?jobId=42"
    )


def test_timestamp_normalization_preserves_precision_and_timezone() -> None:
    assert parse_source_timestamp("2026-09-19") == date(2026, 9, 19)
    assert parse_source_timestamp("2026-09-19T10:30:00+05:30") == datetime(
        2026,
        9,
        19,
        10,
        30,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )
    assert parse_source_timestamp("1726704000000") == datetime(
        2024,
        9,
        19,
        tzinfo=UTC,
    )
    assert parse_source_timestamp("Posted 2 Days Ago") is None
    assert parse_source_timestamp("2026-09-19T10:30:00") is None


def test_job_normalization_preserves_original_fields() -> None:
    policy = load_search_profile(Path("config/search_profile.toml")).location
    job = NormalizedJob(
        schema_version=1,
        company_id="example",
        source_type="example",
        external_job_id="42",
        title_original=" ML–Engineer ",
        title_normalized="temporary",
        location_original="Bangalore / Hyderabad",
        location_normalized=("temporary",),
        published_at=None,
        published_at_raw="2026-09-19",
        date_basis=DateBasis.PUBLISHED,
        canonical_url="https://jobs.example.com/opening?jobId=42&utm_campaign=test",
    )

    normalized = normalize_job(job, location_policy=policy)

    assert normalized.title_original == " ML–Engineer "
    assert normalized.location_original == "Bangalore / Hyderabad"
    assert normalized.title_normalized == "ml engineer"
    assert normalized.location_normalized == ("bengaluru", "hyderabad")
    assert normalized.published_at == date(2026, 9, 19)
    assert normalized.canonical_url == "https://jobs.example.com/opening?jobId=42"
