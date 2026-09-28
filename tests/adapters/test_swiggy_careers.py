"""Fixture-backed tests for Swiggy's public MyNextHire inventory."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError
from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy, HttpResponse
from job_finder.adapters.swiggy_careers import (
    SWIGGY_ADAPTER_KEY,
    SWIGGY_CAREERS_URL,
    SWIGGY_JOBS_API,
    SwiggyCareersAdapter,
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

FIXTURE = Path(__file__).parents[1] / "fixtures" / "swiggy_careers" / "listings.json"


class Transport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, Mapping[str, str], bytes]] = []

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        **_: object,
    ) -> HttpResponse:
        self.calls.append((url, headers, body))
        response = self.responses.pop(0)
        return replace(response, requested_url=url, final_url=response.final_url or url)


def source() -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id="swiggy",
        company_name="Swiggy",
        status=SourceStatus.REVIEWED,
        careers_url=SWIGGY_CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": SWIGGY_ADAPTER_KEY},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "approvedOn",
            DateBasis.UNKNOWN,
            False,
            "Requisition approval time is not verified publication evidence.",
        ),
        detail_strategy=DetailStrategy.LISTING_PAYLOAD,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(SWIGGY_CAREERS_URL, SWIGGY_JOBS_API),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def response(body: bytes, *, final_url: str = "") -> HttpResponse:
    return HttpResponse("", final_url, 200, "application/json", 0, body)


def adapter_for(responses: list[HttpResponse]) -> tuple[SwiggyCareersAdapter, Transport]:
    transport = Transport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return SwiggyCareersAdapter(client), transport


def test_inventory_maps_identity_description_location_and_unknown_date() -> None:
    adapter, transport = adapter_for([response(FIXTURE.read_bytes())])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 1
    assert [job.external_job_id for job in result.jobs] == ["28894", "28829"]
    first = result.jobs[0]
    assert first.title_original == "Sales Manager II"
    assert first.location_normalized == ("kolkata",)
    assert first.date_basis is DateBasis.UNKNOWN
    assert first.published_at is not None
    assert first.published_at.isoformat() == "2026-09-09T04:43:38.697000+00:00"
    assert first.description is not None
    assert "territory planning" in first.description
    assert first.canonical_url.startswith(
        "https://careers.swiggy.com/#/careers?src%3Dcareers%26p%3D"
    )
    assert first.source_metadata["minimum_experience_years"] == 2.0
    assert [item.category for item in result.diagnostics] == ["unverified_approved_on"]
    url, headers, body = transport.calls[0]
    assert url == SWIGGY_JOBS_API
    assert headers["Referer"] == SWIGGY_CAREERS_URL
    assert json.loads(body) == {"source": "careers", "code": "", "filterByBuId": -1}


def test_changed_status_duplicate_and_malformed_location_fail_closed() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["reqDetailsBOList"][0]["statusId"] = 2
    changed, _ = adapter_for([response(json.dumps(payload).encode())])
    assert changed.list_jobs(source()).outcome is AdapterOutcome.FAILED

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["reqDetailsBOList"][1]["reqId"] = 28894
    duplicate, _ = adapter_for([response(json.dumps(payload).encode())])
    assert duplicate.list_jobs(source()).outcome is AdapterOutcome.SUSPICIOUS

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["reqDetailsBOList"][0]["locationList"][0]["address"] = "Mumbai"
    payload["reqDetailsBOList"][0]["locationList"][0]["office"] = "Mumbai"
    malformed, _ = adapter_for([response(json.dumps(payload).encode())])
    assert malformed.list_jobs(source()).outcome is AdapterOutcome.FAILED


def test_short_but_nonempty_source_description_remains_visible_and_measured() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["reqDetailsBOList"][0]["jdDisplay"] = "FM to FEM transition"
    adapter, _ = adapter_for([response(json.dumps(payload).encode())])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.jobs[0].description == "FM to FEM transition"
    assert result.jobs[0].source_metadata["short_description"] is True
    assert [item.category for item in result.diagnostics] == [
        "short_source_description",
        "unverified_approved_on",
    ]


def test_empty_redirect_and_source_configuration_are_strict() -> None:
    empty, _ = adapter_for([response(b'{"reqDetailsBOList":[]}')])
    assert empty.list_jobs(source()).outcome is AdapterOutcome.FAILED

    redirected, _ = adapter_for(
        [response(FIXTURE.read_bytes(), final_url="https://example.com/jobs")]
    )
    assert redirected.list_jobs(source()).outcome is AdapterOutcome.FAILED

    adapter, transport = adapter_for([])
    with pytest.raises(AdapterConfigurationError, match="adapter_key=swiggy_mynexthire"):
        adapter.list_jobs(replace(source(), adapter_parameters={"adapter_key": "other"}))
    with pytest.raises(AdapterConfigurationError, match="requires careers_url"):
        adapter.list_jobs(replace(source(), careers_url="https://careers.swiggy.com/jobs"))
    assert transport.calls == []
