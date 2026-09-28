"""Fixture-backed tests for Quadeye's public Zoho Recruit proxy."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError
from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy, HttpResponse
from job_finder.adapters.quadeye_careers import (
    QUADEYE_ADAPTER_KEY,
    QUADEYE_CAREERS_URL,
    QUADEYE_JOBS_API,
    QuadeyeCareersAdapter,
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

FIXTURE = Path(__file__).parents[1] / "fixtures" / "quadeye_careers" / "jobs.json"


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
        company_id="quadeye",
        company_name="Quadeye",
        status=SourceStatus.REVIEWED,
        careers_url=QUADEYE_CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": QUADEYE_ADAPTER_KEY},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "Date_Opened", DateBasis.UNKNOWN, False, "Zoho opening date has unknown basis."
        ),
        detail_strategy=DetailStrategy.LISTING_PAYLOAD,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(QUADEYE_CAREERS_URL, QUADEYE_JOBS_API),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def payload() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def response(value: dict[str, object], *, final_url: str = "") -> HttpResponse:
    return HttpResponse("", final_url, 200, "application/json", 0, json.dumps(value).encode())


def adapter_for(
    responses: list[HttpResponse],
) -> tuple[QuadeyeCareersAdapter, RouteTransport]:
    transport = RouteTransport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return QuadeyeCareersAdapter(client), transport


def test_complete_collection_maps_identity_location_date_description_and_url() -> None:
    adapter, transport = adapter_for([response(payload())])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 1
    assert len(result.jobs) == 2
    first, second = result.jobs
    assert first.external_job_id == "199893000003455803"
    assert first.location_original == "New York | Chicago"
    assert first.location_normalized == ("new york", "chicago")
    assert first.published_at is not None
    assert first.published_at.isoformat() == "2026-09-08"
    assert first.date_basis is DateBasis.UNKNOWN
    assert first.canonical_url == (
        "https://www.quadeye.com/jobs/199893000003455803/quantitative-researcher?source=CareerSite"
    )
    assert first.description_hash is not None
    assert first.source_metadata["job_opening_status"] == "On-Hold"
    assert second.canonical_url.endswith("/linux-engineer-l2-l3?source=CareerSite")
    assert transport.calls == [QUADEYE_JOBS_API]


def test_schema_visibility_duplicate_and_redirect_fail_closed() -> None:
    hidden = payload()
    hidden["data"][0]["Publish"] = False  # type: ignore[index]
    adapter, _ = adapter_for([response(hidden)])
    result = adapter.list_jobs(source())
    assert result.outcome is AdapterOutcome.FAILED
    assert result.diagnostics[-1].category == "malformed_job"

    duplicate = payload()
    duplicate["data"][1]["id"] = duplicate["data"][0]["id"]  # type: ignore[index]
    adapter, _ = adapter_for([response(duplicate)])
    assert adapter.list_jobs(source()).outcome is AdapterOutcome.SUSPICIOUS

    bad_root = payload()
    bad_root["success"] = False
    adapter, _ = adapter_for([response(bad_root)])
    assert adapter.list_jobs(source()).outcome is AdapterOutcome.FAILED

    adapter, _ = adapter_for([response(payload(), final_url="https://example.com/jobs")])
    assert adapter.list_jobs(source()).outcome is AdapterOutcome.FAILED


def test_source_configuration_is_strict() -> None:
    adapter, transport = adapter_for([])
    with pytest.raises(AdapterConfigurationError, match="adapter_key=quadeye_zoho_proxy"):
        adapter.list_jobs(replace(source(), adapter_parameters={"adapter_key": "other"}))
    with pytest.raises(AdapterConfigurationError, match="requires careers_url"):
        adapter.list_jobs(replace(source(), careers_url="https://quadeye.com/careers"))
    assert transport.calls == []
