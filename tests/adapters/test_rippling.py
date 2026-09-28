"""Fixture-backed tests for Rippling public ATS boards."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError, JobDetailAdapter
from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy, HttpResponse
from job_finder.adapters.rippling import RipplingAdapter
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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "rippling"


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
        careers_url="https://ats.rippling.com/example/jobs",
        adapter_type=AdapterType.RIPPLING,
        adapter_parameters={"board_slug": "example"},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "createdOn", DateBasis.UNKNOWN, False, "Creation time is not verified publication time."
        ),
        detail_strategy=DetailStrategy.DETAIL_PAGE,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=("https://ats.rippling.com/example/jobs",),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def fixture(name: str) -> HttpResponse:
    return HttpResponse("", "", 200, "text/html", 0, (FIXTURES / name).read_bytes())


def adapter_for(responses: list[HttpResponse]) -> tuple[RipplingAdapter, RouteTransport]:
    transport = RouteTransport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return RipplingAdapter(client), transport


def test_complete_embedded_collection_maps_identity_locations_and_remote() -> None:
    adapter, transport = adapter_for([fixture("listing.html")])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 1
    assert [job.external_job_id for job in result.jobs] == [
        "8c314a48-3328-4e77-ba4e-eee852673a58",
        "cf4c5d3f-f79a-40d1-a27c-852e5f9c854f",
    ]
    assert result.jobs[0].location_normalized == ("bengaluru", "india", "hybrid")
    assert result.jobs[1].location_normalized == ("remote - india", "india", "remote")
    assert result.jobs[0].date_basis is DateBasis.UNKNOWN
    assert transport.calls == ["https://ats.rippling.com/example/jobs"]


def test_detail_supplies_description_and_preserves_uncertain_creation_time() -> None:
    adapter, _ = adapter_for([fixture("listing.html"), fixture("detail.html")])
    listing = adapter.list_jobs(source()).jobs[0]

    assert isinstance(adapter, JobDetailAdapter)
    detailed = adapter.get_job_detail(source(), listing)

    assert detailed.external_job_id == listing.external_job_id
    assert detailed.canonical_url == listing.canonical_url
    assert detailed.published_at == datetime.fromisoformat("2026-09-21T10:15:30+05:30")
    assert detailed.published_at_raw == "2026-09-21T10:15:30.000+05:30"
    assert detailed.date_basis is DateBasis.UNKNOWN
    assert detailed.description == (
        "Build speech AI products.\n\nOwn reliable inference services.\n\nPartner with research."
    )
    assert detailed.description_hash is not None


def test_empty_malformed_duplicate_and_unverified_pagination_fail_closed() -> None:
    empty, _ = adapter_for([fixture("empty.html")])
    assert empty.list_jobs(source()).outcome is AdapterOutcome.EMPTY

    malformed, _ = adapter_for([fixture("malformed.html")])
    malformed_result = malformed.list_jobs(source())
    assert malformed_result.outcome is AdapterOutcome.FAILED
    assert malformed_result.diagnostics[-1].category == "malformed_job"

    listing = (FIXTURES / "listing.html").read_text(encoding="utf-8")
    duplicate_html = listing.replace(
        "cf4c5d3f-f79a-40d1-a27c-852e5f9c854f",
        "8c314a48-3328-4e77-ba4e-eee852673a58",
    )
    duplicate, _ = adapter_for([HttpResponse("", "", 200, "text/html", 0, duplicate_html.encode())])
    assert duplicate.list_jobs(source()).diagnostics[-1].category == "duplicate_job_id"

    paginated_html = listing.replace('"totalPages": 1', '"totalPages": 2')
    paginated, _ = adapter_for([HttpResponse("", "", 200, "text/html", 0, paginated_html.encode())])
    assert paginated.list_jobs(source()).diagnostics[-1].category == "unverified_pagination"


def test_invalid_source_configuration_is_rejected_before_network() -> None:
    adapter, transport = adapter_for([fixture("listing.html")])
    with pytest.raises(AdapterConfigurationError):
        adapter.list_jobs(replace(source(), adapter_type=AdapterType.ASHBY))
    with pytest.raises(ValueError, match="letters, digits, and hyphens"):
        adapter.list_jobs(replace(source(), adapter_parameters={"board_slug": "bad/slug"}))
    assert transport.calls == []
