"""Tests for the rolling ten-day rule and H5 measurement contract."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from job_finder.core.job_contracts import DateBasis
from job_finder.core.recency import (
    CompanyDateCoverageClass,
    CompanyDateCoverageInput,
    DateEvidenceStatus,
    ListingDateObservation,
    RecencyAssessment,
    RecencyDecision,
    SourceAssessment,
    assess_listing_recency,
    assess_recency,
    build_date_coverage_report,
)
from job_finder.core.search_profile import DateUncertaintyMode

SCAN_AT = datetime(2026, 9, 20, 12, tzinfo=UTC)


def assess(
    value: datetime | date | None, *, basis: DateBasis = DateBasis.PUBLISHED
) -> RecencyAssessment:
    return assess_recency(
        value,
        basis=basis,
        scan_at=SCAN_AT,
        window_days=10,
        uncertainty_mode=DateUncertaintyMode.MEASURE_THEN_DECIDE,
        publication_date_verified=True,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (SCAN_AT - timedelta(days=10), RecencyDecision.INSIDE_WINDOW),
        (SCAN_AT - timedelta(days=10) + timedelta(seconds=1), RecencyDecision.INSIDE_WINDOW),
        (SCAN_AT - timedelta(days=10) - timedelta(seconds=1), RecencyDecision.OUTSIDE_WINDOW),
    ],
)
def test_exact_rolling_window_boundaries(value: datetime, expected: RecencyDecision) -> None:
    assert assess(value).decision is expected


def test_timezone_offsets_compare_as_instants() -> None:
    india_time = (SCAN_AT - timedelta(days=10)).astimezone(timezone(timedelta(hours=5, minutes=30)))

    result = assess(india_time)

    assert result.decision is RecencyDecision.INSIDE_WINDOW
    assert result.evidence_status is DateEvidenceStatus.RELIABLE


def test_date_only_on_boundary_stays_uncertain_without_invented_precision() -> None:
    result = assess((SCAN_AT - timedelta(days=10)).date())

    assert result.decision is RecencyDecision.UNCERTAIN
    assert result.evidence_status is DateEvidenceStatus.UNCERTAIN
    assert result.measurement_pool is True


def test_date_only_clearly_inside_or_outside_is_decidable() -> None:
    assert assess(date(2026, 9, 19)).decision is RecencyDecision.INSIDE_WINDOW
    assert assess(date(2026, 9, 9)).decision is RecencyDecision.OUTSIDE_WINDOW


def test_missing_date_stays_in_measurement_pool() -> None:
    result = assess(None)

    assert result.decision is RecencyDecision.UNCERTAIN
    assert result.evidence_status is DateEvidenceStatus.MISSING
    assert result.measurement_pool is True


def test_unparseable_verified_publication_date_is_invalid_not_missing() -> None:
    result = assess_listing_recency(
        None,
        raw_date_text="not-a-date",
        basis=DateBasis.PUBLISHED,
        scan_at=SCAN_AT,
        window_days=10,
        uncertainty_mode=DateUncertaintyMode.MEASURE_THEN_DECIDE,
        publication_date_verified=True,
    )

    assert result.decision is RecencyDecision.INVALID
    assert result.evidence_status is DateEvidenceStatus.INVALID


def test_unparsed_non_publication_value_stays_uncertain() -> None:
    result = assess_listing_recency(
        None,
        raw_date_text="Posted 2 Days Ago",
        basis=DateBasis.UNKNOWN,
        scan_at=SCAN_AT,
        window_days=10,
        uncertainty_mode=DateUncertaintyMode.MEASURE_THEN_DECIDE,
        publication_date_verified=False,
    )

    assert result.decision is RecencyDecision.UNCERTAIN
    assert result.evidence_status is DateEvidenceStatus.UNCERTAIN


@pytest.mark.parametrize("basis", [DateBasis.UPDATED, DateBasis.FIRST_SEEN, DateBasis.UNKNOWN])
def test_non_publication_basis_stays_uncertain(basis: DateBasis) -> None:
    result = assess(SCAN_AT - timedelta(days=1), basis=basis)

    assert result.decision is RecencyDecision.UNCERTAIN
    assert result.evidence_status is DateEvidenceStatus.UNCERTAIN


def test_unverified_publication_field_stays_uncertain() -> None:
    result = assess_recency(
        SCAN_AT - timedelta(days=1),
        basis=DateBasis.PUBLISHED,
        scan_at=SCAN_AT,
        window_days=10,
        uncertainty_mode=DateUncertaintyMode.MEASURE_THEN_DECIDE,
        publication_date_verified=False,
    )

    assert result.evidence_status is DateEvidenceStatus.UNCERTAIN


def test_future_timestamp_is_invalid() -> None:
    result = assess(SCAN_AT + timedelta(seconds=1))

    assert result.decision is RecencyDecision.INVALID
    assert result.evidence_status is DateEvidenceStatus.INVALID


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        assess(datetime(2026, 9, 20, 10))


def observation(
    company_id: str,
    adapter_type: str,
    status: DateEvidenceStatus,
    *,
    first_seen: bool = True,
    decision: RecencyDecision = RecencyDecision.UNCERTAIN,
) -> ListingDateObservation:
    return ListingDateObservation(
        company_id=company_id,
        adapter_type=adapter_type,
        evidence_status=status,
        date_basis=(
            DateBasis.PUBLISHED if status is DateEvidenceStatus.RELIABLE else DateBasis.UNKNOWN
        ),
        raw_date_text=("Sep 19, 2026" if status is not DateEvidenceStatus.MISSING else None),
        job_url=f"https://jobs.example.com/{company_id}/{status.value}",
        first_seen_at=(SCAN_AT if first_seen else None),
        decision=decision,
    )


def test_date_coverage_report_contains_all_required_breakdowns() -> None:
    report = build_date_coverage_report(
        [
            CompanyDateCoverageInput(
                company_id="all-reliable",
                company_name="All Reliable",
                adapter_type="greenhouse",
                assessment=SourceAssessment.OBSERVED,
                observations=(
                    observation(
                        "all-reliable",
                        "greenhouse",
                        DateEvidenceStatus.RELIABLE,
                        decision=RecencyDecision.INSIDE_WINDOW,
                    ),
                ),
            ),
            CompanyDateCoverageInput(
                company_id="mixed",
                company_name="Mixed",
                adapter_type="greenhouse",
                assessment=SourceAssessment.OBSERVED,
                observations=(
                    observation("mixed", "greenhouse", DateEvidenceStatus.RELIABLE),
                    observation("mixed", "greenhouse", DateEvidenceStatus.UNCERTAIN),
                    observation("mixed", "greenhouse", DateEvidenceStatus.INVALID),
                    observation(
                        "mixed", "greenhouse", DateEvidenceStatus.MISSING, first_seen=False
                    ),
                ),
            ),
            CompanyDateCoverageInput(
                company_id="none-reliable",
                company_name="None Reliable",
                adapter_type="workday",
                assessment=SourceAssessment.OBSERVED,
                observations=(observation("none-reliable", "workday", DateEvidenceStatus.MISSING),),
            ),
            CompanyDateCoverageInput(
                company_id="empty",
                company_name="Empty",
                adapter_type="workday",
                assessment=SourceAssessment.NO_LISTINGS,
                observations=(),
            ),
            CompanyDateCoverageInput(
                company_id="unassessed",
                company_name="Unassessed",
                adapter_type="custom",
                assessment=SourceAssessment.UNASSESSED,
                observations=(),
            ),
        ]
    )

    assert report.enabled_company_count == 5
    assert report.company_class_counts == {
        CompanyDateCoverageClass.ALL_RELIABLE: 1,
        CompanyDateCoverageClass.MIXED: 1,
        CompanyDateCoverageClass.NO_RELIABLE: 1,
        CompanyDateCoverageClass.NO_LISTINGS: 1,
        CompanyDateCoverageClass.UNASSESSED: 1,
    }
    assert report.listing_counts.reliable == 2
    assert report.listing_counts.uncertain == 1
    assert report.listing_counts.invalid == 1
    assert report.listing_counts.missing == 2
    assert report.listing_percentages["reliable"] == pytest.approx(2 / 6 * 100)
    assert report.decision_counts.inside_window == 1
    assert report.decision_counts.uncertain == 5
    assert report.decision_counts.invalid == 0
    assert report.by_adapter["greenhouse"].company_count == 2
    assert report.by_adapter["workday"].listing_counts.missing == 1
    assert report.first_seen_available_count == 5


def test_date_coverage_rejects_duplicate_company_ids() -> None:
    item = CompanyDateCoverageInput(
        company_id="duplicate",
        company_name="Duplicate",
        adapter_type="greenhouse",
        assessment=SourceAssessment.NO_LISTINGS,
        observations=(),
    )

    with pytest.raises(ValueError, match="duplicate company IDs"):
        build_date_coverage_report([item, item])
