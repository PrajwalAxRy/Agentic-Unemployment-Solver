"""Tests for company, job, adapter-result, and diagnostic contracts."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.core.source_contracts import (
    AdapterDiagnostic,
    AdapterOutcome,
    AdapterResult,
    DiagnosticSeverity,
    company_source_from_mapping,
)


def valid_company_source() -> dict[str, object]:
    return {
        "schema_version": 1,
        "company_id": "example-company",
        "company_name": "Example Company",
        "status": "enabled",
        "careers_url": "https://careers.example.com/jobs",
        "adapter_type": "greenhouse",
        "adapter_parameters": {"board_token": "example"},
        "identity_strategy": "external_id",
        "date_strategy": {
            "field_name": "first_published",
            "basis": "published",
            "verified_as_publication": True,
            "notes": "Verified against public source documentation.",
        },
        "detail_strategy": "listing_payload",
        "enabled": True,
        "confidence": "high",
        "evidence": ["https://careers.example.com/jobs"],
        "low_confidence_approved": False,
        "exception_reason": None,
        "notes": "",
    }


def normalized_job() -> NormalizedJob:
    return NormalizedJob(
        schema_version=1,
        company_id="example-company",
        source_type="greenhouse",
        external_job_id="123",
        title_original="Machine Learning Engineer",
        title_normalized="machine learning engineer",
        location_original="Bengaluru, India",
        location_normalized=("bengaluru", "india"),
        published_at=datetime(2026, 9, 19, 10, tzinfo=UTC),
        published_at_raw="2026-09-19T10:00:00Z",
        date_basis=DateBasis.PUBLISHED,
        canonical_url="https://careers.example.com/jobs/123",
    )


def diagnostic() -> AdapterDiagnostic:
    return AdapterDiagnostic(
        category="parse_error",
        severity=DiagnosticSeverity.ERROR,
        message="Required listing field was missing.",
        context={"field": "title"},
    )


def test_valid_company_source_loads() -> None:
    source = company_source_from_mapping(valid_company_source())

    assert source.company_id == "example-company"
    assert source.adapter_parameters == {"board_token": "example"}
    assert source.enabled is True


def test_adapter_specific_parameters_are_required() -> None:
    raw = valid_company_source()
    raw["adapter_parameters"] = {}

    with pytest.raises(ValueError, match="board_token"):
        company_source_from_mapping(raw)


@pytest.mark.parametrize(
    "careers_url",
    ["careers.example.com/jobs", "file:///tmp/jobs", "https://user:secret@example.com/jobs"],
)
def test_invalid_or_credential_bearing_source_urls_fail(careers_url: str) -> None:
    raw = valid_company_source()
    raw["careers_url"] = careers_url

    with pytest.raises(ValueError, match="careers_url"):
        company_source_from_mapping(raw)


def test_unknown_company_source_schema_version_fails() -> None:
    raw = valid_company_source()
    raw["schema_version"] = 99

    with pytest.raises(ValueError, match="supported=1"):
        company_source_from_mapping(raw)


def test_enabled_low_confidence_source_requires_approval() -> None:
    raw = valid_company_source()
    raw["confidence"] = "low"

    with pytest.raises(ValueError, match="explicit approval"):
        company_source_from_mapping(raw)

    approved = deepcopy(raw)
    approved["low_confidence_approved"] = True
    assert company_source_from_mapping(approved).enabled is True


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("company_id", ""),
        ("title_original", ""),
        ("location_original", ""),
        ("canonical_url", "not-a-url"),
    ],
)
def test_normalized_job_rejects_missing_required_fields(
    field_name: str,
    replacement: str,
) -> None:
    values = {
        "schema_version": 1,
        "company_id": "example-company",
        "source_type": "greenhouse",
        "external_job_id": "123",
        "title_original": "Machine Learning Engineer",
        "title_normalized": "machine learning engineer",
        "location_original": "Bengaluru, India",
        "location_normalized": ("bengaluru", "india"),
        "published_at": datetime(2026, 9, 19, 10, tzinfo=UTC),
        "published_at_raw": "2026-09-19T10:00:00Z",
        "date_basis": DateBasis.PUBLISHED,
        "canonical_url": "https://careers.example.com/jobs/123",
    }
    values[field_name] = replacement

    with pytest.raises(ValueError):
        NormalizedJob(**values)  # type: ignore[arg-type]


def test_valid_empty_board_differs_from_parse_failure() -> None:
    source = company_source_from_mapping(valid_company_source())
    empty = AdapterResult(
        schema_version=1,
        source=source,
        outcome=AdapterOutcome.EMPTY,
        jobs=(),
        page_count=1,
        complete=True,
        diagnostics=(),
    )
    failed = AdapterResult(
        schema_version=1,
        source=source,
        outcome=AdapterOutcome.FAILED,
        jobs=(),
        page_count=1,
        complete=False,
        diagnostics=(diagnostic(),),
    )

    assert empty.outcome is AdapterOutcome.EMPTY
    assert empty.complete is True
    assert failed.outcome is AdapterOutcome.FAILED
    assert failed.complete is False


def test_partial_result_cannot_be_reported_complete() -> None:
    source = company_source_from_mapping(valid_company_source())

    with pytest.raises(ValueError, match="cannot be complete"):
        AdapterResult(
            schema_version=1,
            source=source,
            outcome=AdapterOutcome.PARTIAL,
            jobs=(normalized_job(),),
            page_count=1,
            complete=True,
            diagnostics=(diagnostic(),),
        )


def test_unknown_adapter_result_schema_fails() -> None:
    source = company_source_from_mapping(valid_company_source())

    with pytest.raises(ValueError, match="supported=1"):
        AdapterResult(
            schema_version=2,
            source=source,
            outcome=AdapterOutcome.EMPTY,
            jobs=(),
            page_count=1,
            complete=True,
            diagnostics=(),
        )
