"""Fixture-backed tests for Booking.com's public Jibe inventory."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError
from job_finder.adapters.booking_careers import (
    BOOKING_ADAPTER_KEY,
    BOOKING_CAREERS_URL,
    BookingCareersAdapter,
)
from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy, HttpResponse
from job_finder.core.job_contracts import DateBasis
from job_finder.core.source_contracts import (
    AdapterOutcome,
    AdapterType,
    CompanySource,
    Confidence,
    DateStrategy,
    DetailStrategy,
    IdentityStrategy,
    SourceStatus,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "booking_careers"


class RouteTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **_: object) -> HttpResponse:
        self.calls.append(url)
        response = self.responses.pop(0)
        return replace(response, requested_url=url, final_url=response.final_url or url)


def source() -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id="booking-com",
        company_name="Booking.com",
        status=SourceStatus.REVIEWED,
        careers_url=BOOKING_CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": BOOKING_ADAPTER_KEY},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "posted_date", DateBasis.PUBLISHED, True, "Public Jibe posting timestamp."
        ),
        detail_strategy=DetailStrategy.LISTING_PAYLOAD,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(BOOKING_CAREERS_URL,),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def response(payload: dict[str, object], *, final_url: str = "") -> HttpResponse:
    return HttpResponse("", final_url, 200, "application/json", 0, json.dumps(payload).encode())


def fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def adapter_for(
    responses: list[HttpResponse],
) -> tuple[BookingCareersAdapter, RouteTransport]:
    transport = RouteTransport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return BookingCareersAdapter(client), transport


def test_complete_inventory_reconciles_pages_and_maps_full_payload() -> None:
    adapter, transport = adapter_for(
        [response(fixture("page1.json")), response(fixture("page2.json"))]
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 2
    assert len(result.jobs) == 11
    first = result.jobs[0]
    assert first.external_job_id == "30001"
    assert first.title_normalized == "machine learning engineer"
    assert first.location_normalized == ("bengaluru", "india")
    assert first.date_basis is DateBasis.PUBLISHED
    assert first.published_at is not None
    assert first.published_at.isoformat() == "2026-09-28T10:00:00+05:30"
    assert first.canonical_url == "https://jobs.booking.com/booking/jobs/30001?lang=en-us"
    assert first.description == (
        "Build production machine-learning systems.\n\nTrain models.\n\nEvaluate reliability."
    )
    assert first.description_hash is not None
    assert first.source_metadata["category"] == ("Engineering", "Data Science")
    assert transport.calls == [
        "https://jobs.booking.com/api/jobs?page=1&sortBy=relevance&descending=false&internal=false&tags1=Booking.com%20Company%20Hierarchy%7CTransport%20Company%20Hierarchy",
        "https://jobs.booking.com/api/jobs?page=2&sortBy=relevance&descending=false&internal=false&tags1=Booking.com%20Company%20Hierarchy%7CTransport%20Company%20Hierarchy",
    ]


def test_total_drift_short_page_duplicate_and_redirect_fail_closed() -> None:
    first = fixture("page1.json")
    second = fixture("page2.json")
    second["totalCount"] = 12
    second["count"] = 12
    drift, _ = adapter_for([response(first), response(second)])
    assert drift.list_jobs(source()).outcome is AdapterOutcome.SUSPICIOUS

    short = fixture("page1.json")
    short["jobs"].pop()  # type: ignore[union-attr]
    incomplete, _ = adapter_for([response(short)])
    incomplete_result = incomplete.list_jobs(source())
    assert incomplete_result.outcome is AdapterOutcome.SUSPICIOUS
    assert incomplete_result.diagnostics[-1].category == "incomplete_page"

    first = fixture("page1.json")
    second = fixture("page2.json")
    second["jobs"][0]["data"]["req_id"] = "30001"  # type: ignore[index]
    second["jobs"][0]["data"]["slug"] = "30001"  # type: ignore[index]
    second["jobs"][0]["data"]["apply_url"] = (  # type: ignore[index]
        "https://external-workingatbooking.icims.com/jobs/30001/login"
    )
    second["jobs"][0]["data"]["meta_data"]["canonical_url"] = (  # type: ignore[index]
        "https://jobs.booking.com/booking/jobs/30001?lang=en-us"
    )
    duplicate, _ = adapter_for([response(first), response(second)])
    assert duplicate.list_jobs(source()).outcome is AdapterOutcome.SUSPICIOUS

    redirected, _ = adapter_for(
        [response(fixture("page1.json"), final_url="https://example.com/api/jobs")]
    )
    assert redirected.list_jobs(source()).outcome is AdapterOutcome.FAILED


def test_malformed_visibility_url_date_and_source_configuration_fail_closed() -> None:
    for mutate in ("internal", "url", "date"):
        payload = fixture("page1.json")
        data = payload["jobs"][0]["data"]  # type: ignore[index]
        if mutate == "internal":
            data["internal"] = True  # type: ignore[index]
        elif mutate == "url":
            data["meta_data"]["canonical_url"] = (  # type: ignore[index]
                "https://example.com/booking/jobs/30001?lang=en-us"
            )
        else:
            data["posted_date"] = "today"  # type: ignore[index]
        adapter, _ = adapter_for([response(payload)])
        result = adapter.list_jobs(source())
        assert result.outcome is AdapterOutcome.FAILED
        assert result.diagnostics[-1].category == "malformed_job"

    configured, transport = adapter_for([])
    with pytest.raises(AdapterConfigurationError, match="adapter_key=booking_jibe_inventory"):
        configured.list_jobs(replace(source(), adapter_parameters={"adapter_key": "other"}))
    with pytest.raises(AdapterConfigurationError, match="requires careers_url"):
        configured.list_jobs(replace(source(), careers_url="https://careers.booking.com"))
    assert transport.calls == []
