"""Fixture-backed tests for SenseHQ public career portals."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError
from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy, HttpResponse
from job_finder.adapters.sensehq import SenseHqAdapter
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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "sensehq"


class RouteTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **_: object) -> HttpResponse:
        self.calls.append(url)
        return replace(self.responses.pop(0), requested_url=url, final_url=url)


def source() -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id="example",
        company_name="Example",
        status=SourceStatus.REVIEWED,
        careers_url="https://example.sensehq.com/careers",
        adapter_type=AdapterType.SENSEHQ,
        adapter_parameters={"career_subdomain": "example"},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "created_on", DateBasis.UNKNOWN, False, "Creation time is not publication time."
        ),
        detail_strategy=DetailStrategy.LISTING_PAYLOAD,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=("https://example.sensehq.com/careers",),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def fixture(name: str) -> HttpResponse:
    return HttpResponse("", "", 200, "text/html", 0, (FIXTURES / name).read_bytes())


def adapter_for(
    responses: list[HttpResponse], *, max_pages: int = 10
) -> tuple[SenseHqAdapter, RouteTransport]:
    transport = RouteTransport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return SenseHqAdapter(client, page_size=2, max_pages=max_pages), transport


def test_count_checked_pagination_maps_descriptions_identity_dates_and_locations() -> None:
    adapter, transport = adapter_for([fixture("page_1.html"), fixture("page_2.html")])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 2
    assert [job.external_job_id for job in result.jobs] == ["101", "102", "103"]
    assert result.jobs[0].canonical_url == "https://example.sensehq.com/careers/jobs/101"
    assert result.jobs[0].location_normalized == (
        "bangalore",
        "karnataka",
        "india",
        "hybrid",
    )
    assert result.jobs[0].description == "Build reliable AI services.\n\nPartner with research."
    assert result.jobs[0].published_at == datetime(2026, 9, 22, 21, 20, tzinfo=UTC)
    assert result.jobs[0].date_basis is DateBasis.UNKNOWN
    assert result.jobs[1].description is None
    assert result.diagnostics[-1].category == "missing_descriptions"
    assert "page=0&pageSize=2" in transport.calls[0]
    assert "page=1&pageSize=2" in transport.calls[1]


def test_empty_malformed_duplicate_and_page_limit_are_visible() -> None:
    empty, _ = adapter_for([fixture("empty.html")])
    assert empty.list_jobs(source()).outcome is AdapterOutcome.EMPTY

    malformed, _ = adapter_for([fixture("malformed.html")])
    malformed_result = malformed.list_jobs(source())
    assert malformed_result.outcome is AdapterOutcome.FAILED
    assert malformed_result.diagnostics[-1].category == "malformed_job"

    duplicate, _ = adapter_for([fixture("page_1.html"), fixture("page_1.html")])
    assert duplicate.list_jobs(source()).diagnostics[-1].category == "duplicate_job_id"

    limited, _ = adapter_for([fixture("page_1.html")], max_pages=1)
    assert limited.list_jobs(source()).diagnostics[-1].category == "pagination_limit"


def test_invalid_source_configuration_is_rejected_before_network() -> None:
    adapter, transport = adapter_for([fixture("empty.html")])
    with pytest.raises(AdapterConfigurationError):
        adapter.list_jobs(replace(source(), adapter_type=AdapterType.ASHBY))
    with pytest.raises(ValueError, match="letters, digits, and hyphens"):
        adapter.list_jobs(
            replace(source(), adapter_parameters={"career_subdomain": "bad/subdomain"})
        )
    assert transport.calls == []
