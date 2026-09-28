"""Fixture-backed tests for Google's public India careers search."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError
from job_finder.adapters.google_careers import (
    GOOGLE_CAREERS_ADAPTER_KEY,
    GOOGLE_CAREERS_URL,
    GoogleCareersAdapter,
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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "google_careers"


class RouteTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **_: object) -> HttpResponse:
        self.calls.append(url)
        response = self.responses.pop(0)
        return replace(response, requested_url=url, final_url=url)


def source() -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id="google",
        company_name="Google",
        status=SourceStatus.REVIEWED,
        careers_url=GOOGLE_CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": GOOGLE_CAREERS_ADAPTER_KEY},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            None, DateBasis.UNKNOWN, False, "Google Careers exposes no publication date."
        ),
        detail_strategy=DetailStrategy.DETAIL_PAGE,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(GOOGLE_CAREERS_URL,),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def fixture(name: str) -> HttpResponse:
    return HttpResponse("", "", 200, "text/html", 0, (FIXTURES / name).read_bytes())


def adapter_for(
    responses: list[HttpResponse], *, page_size: int = 1
) -> tuple[GoogleCareersAdapter, RouteTransport]:
    transport = RouteTransport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return GoogleCareersAdapter(client, page_size=page_size), transport


def test_count_checked_pagination_maps_stable_google_job_identity() -> None:
    adapter, transport = adapter_for([fixture("page_1.html"), fixture("page_2.html")])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 2
    assert [job.external_job_id for job in result.jobs] == ["111", "222"]
    first = result.jobs[0]
    assert first.canonical_url == (
        "https://www.google.com/about/careers/applications/jobs/results/"
        "111-machine-learning-engineer"
    )
    assert first.location_original == ("Bengaluru, Karnataka, India | Hyderabad, Telangana, India")
    assert first.location_normalized == (
        "bengaluru",
        "karnataka",
        "india",
        "hyderabad",
        "telangana",
    )
    assert first.published_at is None
    assert first.date_basis is DateBasis.UNKNOWN
    assert first.description is None
    assert first.source_metadata == {
        "adapter_key": GOOGLE_CAREERS_ADAPTER_KEY,
        "product": "Google",
        "experience_level": "Early",
        "listing_minimum_qualifications": (
            "Minimum qualifications\nBachelor's degree or equivalent practical experience."
        ),
        "india_search_result": True,
    }
    assert result.jobs[1].source_metadata["product"] == "YouTube"
    assert transport.calls == [GOOGLE_CAREERS_URL, f"{GOOGLE_CAREERS_URL}&page=2"]


def test_detail_page_maps_all_substantive_sections_and_preserves_identity() -> None:
    adapter, _ = adapter_for([fixture("page_1.html"), fixture("page_2.html")])
    listed = adapter.list_jobs(source()).jobs[0]
    detail_adapter, transport = adapter_for([fixture("detail.html")])

    detailed = detail_adapter.get_job_detail(source(), listed)

    assert detailed.external_job_id == listed.external_job_id
    assert detailed.canonical_url == listed.canonical_url
    assert detailed.description == (
        "Minimum qualifications\n\n"
        "Bachelor's degree or equivalent practical experience.\n"
        "2 years of experience with machine learning.\n\n"
        "Preferred qualifications\n\n"
        "Experience deploying production models.\n\n"
        "About the job\n\n"
        "Build machine learning systems for users.\n\n"
        "Responsibilities\n\n"
        "Design and evaluate models.\n"
        "Collaborate with engineers."
    )
    assert detailed.description_hash is not None
    assert "INTERNAL_PAGE_STATE" not in detailed.description
    assert detailed.source_metadata["product"] == "Google"
    assert detailed.source_metadata["experience_level"] == "Early"
    assert transport.calls == [listed.canonical_url]


def test_india_search_preserves_cross_location_rows_for_downstream_filtering() -> None:
    page = (
        (FIXTURES / "page_1.html")
        .read_text(encoding="utf-8")
        .replace("Bengaluru, Karnataka, India", "Singapore")
        .replace("Hyderabad, Telangana, India", "Sydney NSW, Australia")
    )
    adapter, _ = adapter_for(
        [HttpResponse("", "", 200, "text/html", 0, page.encode()), fixture("page_2.html")]
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.jobs[0].location_original == "Singapore | Sydney NSW, Australia"
    assert result.jobs[0].source_metadata["india_search_result"] is True


def test_malformed_duplicate_and_count_drift_fail_closed() -> None:
    malformed_html = (
        (FIXTURES / "page_1.html")
        .read_text(encoding="utf-8")
        .replace('data-id="111"', 'data-id="999"')
    )
    malformed, _ = adapter_for([HttpResponse("", "", 200, "text/html", 0, malformed_html.encode())])
    malformed_result = malformed.list_jobs(source())
    assert malformed_result.outcome is AdapterOutcome.FAILED
    assert malformed_result.diagnostics[-1].category == "malformed_job"

    duplicate, _ = adapter_for([fixture("page_1.html"), fixture("page_1.html")])
    duplicate_result = duplicate.list_jobs(source())
    assert duplicate_result.outcome is AdapterOutcome.SUSPICIOUS
    assert duplicate_result.diagnostics[-1].category == "duplicate_job_id"

    changed_html = (
        (FIXTURES / "page_2.html")
        .read_text(encoding="utf-8")
        .replace('<span class="SWhIm">2</span>', '<span class="SWhIm">3</span>')
    )
    drift, _ = adapter_for(
        [
            fixture("page_1.html"),
            HttpResponse("", "", 200, "text/html", 0, changed_html.encode()),
        ]
    )
    drift_result = drift.list_jobs(source())
    assert drift_result.outcome is AdapterOutcome.SUSPICIOUS
    assert drift_result.diagnostics[-1].category == "changing_total"


def test_invalid_source_configuration_is_rejected_before_network() -> None:
    adapter, transport = adapter_for([fixture("page_1.html")])
    with pytest.raises(AdapterConfigurationError, match="adapter_key=google_careers_india"):
        adapter.list_jobs(replace(source(), adapter_parameters={"adapter_key": "other"}))
    with pytest.raises(AdapterConfigurationError, match="requires careers_url"):
        adapter.list_jobs(replace(source(), careers_url="https://google.com/careers"))
    assert transport.calls == []
