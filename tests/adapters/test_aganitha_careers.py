"""Fixture-backed tests for Aganitha's official careers inventory."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.aganitha_careers import (
    AGANITHA_ADAPTER_KEY,
    AGANITHA_CAREERS_URL,
    AganithaCareersAdapter,
)
from job_finder.adapters.base import AdapterConfigurationError
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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "aganitha_careers"


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
        company_id="aganitha",
        company_name="Aganitha",
        status=SourceStatus.REVIEWED,
        careers_url=AGANITHA_CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": AGANITHA_ADAPTER_KEY},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(None, DateBasis.UNKNOWN, False, "No verified job date."),
        detail_strategy=DetailStrategy.DETAIL_PAGE,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(AGANITHA_CAREERS_URL,),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def response(body: bytes, *, final_url: str = "") -> HttpResponse:
    return HttpResponse("", final_url, 200, "text/html", 0, body)


def fixture(name: str, *, final_url: str = "") -> HttpResponse:
    return response((FIXTURES / name).read_bytes(), final_url=final_url)


def adapter_for(responses: list[HttpResponse]) -> tuple[AganithaCareersAdapter, RouteTransport]:
    transport = RouteTransport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return AganithaCareersAdapter(client), transport


def test_index_maps_titles_locations_and_deferred_descriptions() -> None:
    adapter, transport = adapter_for(
        [fixture("listing.html"), fixture("detail_one.html"), fixture("detail_two.html")]
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 3
    assert [job.external_job_id for job in result.jobs] == [
        "jr-full-stack-developer",
        "scientist-ai-modeling",
    ]
    first = result.jobs[0]
    assert first.title_original == "Jr Full Stack Developer"
    assert first.location_original == "Hyderabad, India | Hybrid | Full-Time"
    assert first.location_normalized == ("hyderabad", "india", "hybrid", "full-time")
    assert first.date_basis is DateBasis.UNKNOWN
    assert first.published_at is None
    assert first.description is None
    assert result.diagnostics[-1].category == "missing_publication_date"
    assert any(item.category == "title_variation_normalized" for item in result.diagnostics)
    assert transport.calls == [
        AGANITHA_CAREERS_URL,
        "https://www.aganitha.ai/careers/jr-full-stack-developer/",
        "https://www.aganitha.ai/careers/scientist-ai-modeling/",
    ]

    detail_adapter, _ = adapter_for([fixture("detail_one.html")])
    detailed = detail_adapter.get_job_detail(source(), first)
    assert detailed.description is not None
    assert "digital backbone" in detailed.description
    assert "recommendation" not in detailed.description
    assert detailed.description_hash is not None


def test_incomplete_empty_mismatch_and_redirect_fail_closed() -> None:
    listing = (FIXTURES / "listing.html").read_text(encoding="utf-8")
    incomplete, _ = adapter_for(
        [
            response(
                listing.replace(
                    "https://www.aganitha.ai/careers/jr-full-stack-developer/",
                    "#",
                    1,
                ).encode()
            )
        ]
    )
    assert incomplete.list_jobs(source()).outcome is AdapterOutcome.FAILED

    empty, _ = adapter_for([response(b"<html><body><h1>Careers</h1></body></html>")])
    assert empty.list_jobs(source()).outcome is AdapterOutcome.FAILED

    mismatch_detail = (FIXTURES / "detail_one.html").read_text(encoding="utf-8").replace(
        "Jr Full Stack Developer", "Different Role"
    )
    mismatch, _ = adapter_for([fixture("listing.html"), response(mismatch_detail.encode())])
    assert mismatch.list_jobs(source()).outcome is AdapterOutcome.FAILED

    redirected, _ = adapter_for(
        [fixture("listing.html", final_url="https://example.com/careers")]
    )
    assert redirected.list_jobs(source()).outcome is AdapterOutcome.FAILED


def test_source_configuration_is_rejected_before_network() -> None:
    adapter, transport = adapter_for([])
    with pytest.raises(AdapterConfigurationError, match="adapter_key=aganitha_careers_index"):
        adapter.list_jobs(replace(source(), adapter_parameters={"adapter_key": "other"}))
    with pytest.raises(AdapterConfigurationError, match="requires careers_url"):
        adapter.list_jobs(replace(source(), careers_url="https://www.aganitha.ai/jobs/"))
    assert transport.calls == []
