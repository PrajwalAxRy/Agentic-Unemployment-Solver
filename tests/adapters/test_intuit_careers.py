"""Fixture-backed tests for Intuit's public Bengaluru TalentBrew pages."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError, JobDetailAdapter
from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy, HttpResponse
from job_finder.adapters.intuit_careers import (
    INTUIT_ADAPTER_KEY,
    INTUIT_CAREERS_URL,
    IntuitCareersAdapter,
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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "intuit_careers"


class Transport:
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
        company_id="intuit",
        company_name="Intuit",
        status=SourceStatus.REVIEWED,
        careers_url=INTUIT_CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": INTUIT_ADAPTER_KEY},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "JobPosting.datePosted",
            DateBasis.PUBLISHED,
            True,
            "Public JobPosting datePosted on the detail page.",
        ),
        detail_strategy=DetailStrategy.DETAIL_PAGE,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(INTUIT_CAREERS_URL,),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def response(name: str, *, final_url: str = "") -> HttpResponse:
    return HttpResponse("", final_url, 200, "text/html", 0, (FIXTURES / name).read_bytes())


def raw_response(body: bytes, *, final_url: str = "") -> HttpResponse:
    return HttpResponse("", final_url, 200, "text/html", 0, body)


def adapter_for(responses: list[HttpResponse]) -> tuple[IntuitCareersAdapter, Transport]:
    transport = Transport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return IntuitCareersAdapter(client), transport


def test_inventory_and_detail_preserve_filtered_location_and_published_date() -> None:
    adapter, transport = adapter_for([response("page1.html"), response("detail.html")])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 1
    assert [job.external_job_id for job in result.jobs] == ["1001", "1002"]
    first, second = result.jobs
    assert first.location_normalized == ("bangalore", "india")
    assert second.location_original == "Bangalore, India | Multiple Locations"
    assert second.source_metadata["listing_location_original"] == "Multiple Locations"
    assert first.description is None
    assert first.date_basis is DateBasis.UNKNOWN
    assert result.diagnostics[0].category == "publication_date_requires_detail"
    assert isinstance(adapter, JobDetailAdapter)

    detailed = adapter.get_job_detail(source(), first)

    assert detailed.location_original == "Bengaluru, Karnataka, India"
    assert detailed.date_basis is DateBasis.PUBLISHED
    assert detailed.published_at is not None
    assert detailed.published_at.isoformat() == "2026-09-28"
    assert detailed.description is not None
    assert "machine-learning systems" in detailed.description
    assert transport.calls == [INTUIT_CAREERS_URL, first.canonical_url]


def test_count_duplicate_and_redirect_fail_closed() -> None:
    document = (FIXTURES / "page1.html").read_text(encoding="utf-8")
    changed, _ = adapter_for(
        [raw_response(document.replace("2 jobs found", "16 jobs found").encode())]
    )
    assert changed.list_jobs(source()).outcome is AdapterOutcome.SUSPICIOUS

    duplicate_document = document.replace(
        "/job/bengaluru/data-scientist/27595/1002",
        "/job/bengaluru/data-scientist/27595/1001",
    )
    duplicate, _ = adapter_for([raw_response(duplicate_document.encode())])
    assert duplicate.list_jobs(source()).outcome is AdapterOutcome.SUSPICIOUS

    redirected, _ = adapter_for([response("page1.html", final_url="https://jobs.intuit.com/")])
    assert redirected.list_jobs(source()).outcome is AdapterOutcome.FAILED


def test_detail_schema_and_source_configuration_are_strict() -> None:
    adapter, _ = adapter_for([response("page1.html")])
    job = adapter.list_jobs(source()).jobs[0]
    document = (FIXTURES / "detail.html").read_text(encoding="utf-8")
    wrong_country = document.replace('"addressCountry":"India"', '"addressCountry":"US"')
    broken, _ = adapter_for([raw_response(wrong_country.encode())])
    with pytest.raises(ValueError, match="Bengaluru filter location"):
        broken.get_job_detail(source(), job)

    strict, transport = adapter_for([])
    with pytest.raises(AdapterConfigurationError, match="adapter_key=intuit_bengaluru"):
        strict.list_jobs(replace(source(), adapter_parameters={"adapter_key": "other"}))
    with pytest.raises(AdapterConfigurationError, match="requires careers_url"):
        strict.list_jobs(replace(source(), careers_url="https://jobs.intuit.com/search-jobs"))
    assert transport.calls == []
