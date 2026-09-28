"""Fixture-backed tests for Microsoft's public India careers API."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError
from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy, HttpResponse
from job_finder.adapters.microsoft_careers import (
    MICROSOFT_CAREERS_ADAPTER_KEY,
    MICROSOFT_CAREERS_URL,
    MicrosoftCareersAdapter,
)
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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "microsoft_careers"


class RouteTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str | None]] = []

    def get(self, url: str, **kwargs: object) -> HttpResponse:
        headers = kwargs.get("headers")
        referer = headers.get("Referer") if isinstance(headers, dict) else None
        self.calls.append((url, referer if isinstance(referer, str) else None))
        return replace(self.responses.pop(0), requested_url=url, final_url=url)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.delays: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)
        self.now += seconds


def source() -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id="microsoft",
        company_name="Microsoft",
        status=SourceStatus.REVIEWED,
        careers_url=MICROSOFT_CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": MICROSOFT_CAREERS_ADAPTER_KEY},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "postedTs", DateBasis.PUBLISHED, True, "Microsoft publication timestamp."
        ),
        detail_strategy=DetailStrategy.DETAIL_PAGE,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(MICROSOFT_CAREERS_URL,),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def fixture(name: str) -> HttpResponse:
    return HttpResponse("", "", 200, "application/json", 0, (FIXTURES / name).read_bytes())


def adapter_for(
    responses: list[HttpResponse], *, page_size: int = 1
) -> tuple[MicrosoftCareersAdapter, RouteTransport]:
    transport = RouteTransport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return (
        MicrosoftCareersAdapter(client, page_size=page_size, request_interval_seconds=0),
        transport,
    )


def test_count_checked_pagination_maps_ids_dates_and_locations() -> None:
    adapter, transport = adapter_for([fixture("page_1.json"), fixture("page_2.json")])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 2
    assert [job.external_job_id for job in result.jobs] == ["200047138", "200047999"]
    first = result.jobs[0]
    assert first.canonical_url == (
        "https://apply.careers.microsoft.com/careers/job/1970393556957363"
    )
    assert first.location_original == "India, Multiple Locations, Multiple Locations"
    assert first.location_normalized == ("india", "multiple locations")
    assert first.published_at == datetime.fromtimestamp(1786076561, tz=UTC)
    assert first.published_at_raw == "1786076561"
    assert first.date_basis is DateBasis.PUBLISHED
    assert first.description is None
    assert first.source_metadata == {
        "adapter_key": MICROSOFT_CAREERS_ADAPTER_KEY,
        "position_id": "1970393556957363",
        "display_job_id": "200047138",
        "department": "Engineering",
        "standardized_locations": ("IN",),
        "work_location_option": "onsite",
        "location_flexibility": "On-site",
        "india_search_result": True,
    }
    assert transport.calls == [
        (
            "https://apply.careers.microsoft.com/api/pcsx/search?"
            "domain=microsoft.com&query=&location=India&start=0&sort_by=relevance&hl=en",
            MICROSOFT_CAREERS_URL,
        ),
        (
            "https://apply.careers.microsoft.com/api/pcsx/search?"
            "domain=microsoft.com&query=&location=India&start=1&sort_by=relevance&hl=en",
            MICROSOFT_CAREERS_URL,
        ),
    ]


def test_detail_maps_full_description_and_cross_checks_identity() -> None:
    listing_adapter, _ = adapter_for([fixture("page_1.json"), fixture("page_2.json")])
    listed = listing_adapter.list_jobs(source()).jobs[0]
    detail_adapter, transport = adapter_for([fixture("detail.json")])

    detailed = detail_adapter.get_job_detail(source(), listed)

    assert detailed.external_job_id == listed.external_job_id
    assert detailed.canonical_url == listed.canonical_url
    assert detailed.description == (
        "Overview\n\nBuild verification systems for Microsoft silicon.\n\n"
        "Qualifications\n\n3+ years of relevant engineering experience.\n\n"
        "Experience with SystemVerilog.\n\nResponsibilities\n\n"
        "Design and verify complex systems."
    )
    assert detailed.description_hash is not None
    assert detailed.source_metadata["employment_type"] == "Full-Time"
    assert detailed.source_metadata["required_travel"] == "0-25%"
    assert detailed.source_metadata["role_type"] == "Individual Contributor"
    assert detailed.source_metadata["work_site"] == "Up to 50% work from home"
    assert transport.calls == [
        (
            "https://apply.careers.microsoft.com/api/pcsx/position_details?"
            "position_id=1970393556957363&domain=microsoft.com&hl=en",
            MICROSOFT_CAREERS_URL,
        )
    ]


def test_default_request_spacing_is_enforced_between_pages() -> None:
    transport = RouteTransport([fixture("page_1.json"), fixture("page_2.json")])
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    clock = FakeClock()
    adapter = MicrosoftCareersAdapter(
        client,
        page_size=1,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert clock.delays == [7.0]


def test_rolling_request_budget_waits_in_bounded_chunks() -> None:
    payloads = []
    for position_id, job_id in ((101, "201"), (102, "202"), (103, "203")):
        payload = json.loads((FIXTURES / "page_1.json").read_text(encoding="utf-8"))
        payload["data"]["count"] = 3
        row = payload["data"]["positions"][0]
        row["id"] = position_id
        row["displayJobId"] = job_id
        row["atsJobId"] = job_id
        row["positionUrl"] = f"/careers/job/{position_id}"
        payloads.append(
            HttpResponse("", "", 200, "application/json", 0, json.dumps(payload).encode())
        )
    transport = RouteTransport(payloads)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    clock = FakeClock()
    adapter = MicrosoftCareersAdapter(
        client,
        page_size=1,
        request_interval_seconds=0,
        max_requests_per_window=2,
        request_window_seconds=60,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert clock.delays == [30.0, 30.0]


def test_malformed_duplicate_count_drift_and_remote_error_fail_closed() -> None:
    malformed_payload = json.loads((FIXTURES / "page_1.json").read_text(encoding="utf-8"))
    malformed_payload["data"]["positions"][0]["postedTs"] = "yesterday"
    malformed, _ = adapter_for(
        [HttpResponse("", "", 200, "application/json", 0, json.dumps(malformed_payload).encode())]
    )
    malformed_result = malformed.list_jobs(source())
    assert malformed_result.outcome is AdapterOutcome.FAILED
    assert malformed_result.diagnostics[-1].category == "malformed_job"

    duplicate, _ = adapter_for([fixture("page_1.json"), fixture("page_1.json")])
    duplicate_result = duplicate.list_jobs(source())
    assert duplicate_result.outcome is AdapterOutcome.SUSPICIOUS
    assert duplicate_result.diagnostics[-1].category == "duplicate_job_id"

    changed_payload = json.loads((FIXTURES / "page_2.json").read_text(encoding="utf-8"))
    changed_payload["data"]["count"] = 3
    drift, _ = adapter_for(
        [
            fixture("page_1.json"),
            HttpResponse("", "", 200, "application/json", 0, json.dumps(changed_payload).encode()),
        ]
    )
    drift_result = drift.list_jobs(source())
    assert drift_result.outcome is AdapterOutcome.SUSPICIOUS
    assert drift_result.diagnostics[-1].category == "changing_total"

    error_payload = {
        "data": {},
        "error": {"message": "Please try again later", "body": ""},
        "metadata": None,
        "status": 429,
    }
    remote_error, _ = adapter_for(
        [HttpResponse("", "", 200, "application/json", 0, json.dumps(error_payload).encode())]
    )
    error_result = remote_error.list_jobs(source())
    assert error_result.outcome is AdapterOutcome.FAILED
    assert error_result.diagnostics[-1].category == "remote_api_error"


def test_invalid_source_configuration_is_rejected_before_network() -> None:
    adapter, transport = adapter_for([fixture("page_1.json")])
    with pytest.raises(AdapterConfigurationError, match="adapter_key=microsoft_careers_india"):
        adapter.list_jobs(replace(source(), adapter_parameters={"adapter_key": "other"}))
    with pytest.raises(AdapterConfigurationError, match="requires careers_url"):
        adapter.list_jobs(replace(source(), careers_url="https://careers.microsoft.com"))
    assert transport.calls == []
