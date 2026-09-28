"""Fixture-backed tests for public Recruiterflow job boards."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError, JobDetailAdapter
from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy, HttpResponse
from job_finder.adapters.recruiterflow import RecruiterflowAdapter
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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "recruiterflow"


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
        careers_url="https://recruiterflow.com/example/jobs",
        adapter_type=AdapterType.RECRUITERFLOW,
        adapter_parameters={"board_slug": "example"},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "datePosted", DateBasis.PUBLISHED, True, "JSON-LD JobPosting publication date."
        ),
        detail_strategy=DetailStrategy.DETAIL_PAGE,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=("https://recruiterflow.com/example/jobs",),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def fixture(name: str) -> HttpResponse:
    return HttpResponse("", "", 200, "text/html", 0, (FIXTURES / name).read_bytes())


def adapter_for(responses: list[HttpResponse]) -> tuple[RecruiterflowAdapter, RouteTransport]:
    transport = RouteTransport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return RecruiterflowAdapter(client), transport


def test_embedded_department_collection_is_canonical_and_views_are_cross_checked() -> None:
    adapter, transport = adapter_for([fixture("listing.html")])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 1
    assert [job.external_job_id for job in result.jobs] == ["662", "703"]
    assert result.jobs[0].location_normalized == ("bangalore", "india", "hybrid")
    assert result.jobs[0].published_at is None
    assert result.jobs[0].date_basis is DateBasis.UNKNOWN
    assert transport.calls == ["https://recruiterflow.com/example/jobs"]


def test_detail_uses_jobposting_description_location_and_publication_date() -> None:
    adapter, _ = adapter_for([fixture("listing.html"), fixture("detail.html")])
    listing = adapter.list_jobs(source()).jobs[0]

    assert isinstance(adapter, JobDetailAdapter)
    detailed = adapter.get_job_detail(source(), listing)

    assert detailed.external_job_id == "662"
    assert detailed.canonical_url == listing.canonical_url
    assert detailed.title_original == "Enterprise Security Engineer"
    assert detailed.location_normalized == ("bangalore", "karnataka", "india")
    assert detailed.published_at == date(2026, 4, 8)
    assert detailed.published_at_raw == "2026-04-08"
    assert detailed.date_basis is DateBasis.PUBLISHED
    assert detailed.description == (
        "Protect the production platform.\n\nBuild security automation.\n\n"
        "Partner with engineering."
    )
    assert detailed.description_hash is not None


def test_empty_and_mismatched_repeated_views_fail_closed() -> None:
    empty, _ = adapter_for([fixture("empty.html")])
    empty_result = empty.list_jobs(source())
    assert empty_result.outcome is AdapterOutcome.EMPTY
    assert empty_result.complete is True

    mismatched, _ = adapter_for([fixture("mismatched_views.html")])
    mismatch_result = mismatched.list_jobs(source())
    assert mismatch_result.outcome is AdapterOutcome.SUSPICIOUS
    assert mismatch_result.diagnostics[-1].category == "inconsistent_collection_views"


def test_invalid_source_configuration_is_rejected_before_network() -> None:
    adapter, transport = adapter_for([fixture("listing.html")])
    with pytest.raises(AdapterConfigurationError):
        adapter.list_jobs(replace(source(), adapter_type=AdapterType.ASHBY))
    with pytest.raises(ValueError, match="letters, digits, and hyphens"):
        adapter.list_jobs(replace(source(), adapter_parameters={"board_slug": "bad/slug"}))
    assert transport.calls == []
