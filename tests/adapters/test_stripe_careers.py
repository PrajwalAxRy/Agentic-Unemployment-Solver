"""Fixture-backed tests for Stripe's public embedded careers index."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError
from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy, HttpResponse
from job_finder.adapters.stripe_careers import (
    STRIPE_CAREERS_ADAPTER_KEY,
    STRIPE_CAREERS_URL,
    StripeCareersAdapter,
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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "stripe_careers"


class RouteTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **_: object) -> HttpResponse:
        self.calls.append(url)
        response = self.responses.pop(0)
        return replace(
            response,
            requested_url=url,
            final_url=response.final_url or url,
        )


def source() -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id="stripe",
        company_name="Stripe",
        status=SourceStatus.REVIEWED,
        careers_url=STRIPE_CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": STRIPE_CAREERS_ADAPTER_KEY},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "datePosted", DateBasis.PUBLISHED, True, "Stripe detail JobPosting date."
        ),
        detail_strategy=DetailStrategy.DETAIL_PAGE,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(STRIPE_CAREERS_URL,),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def fixture(name: str) -> HttpResponse:
    return HttpResponse("", "", 200, "text/html", 0, (FIXTURES / name).read_bytes())


def adapter_for(responses: list[HttpResponse]) -> tuple[StripeCareersAdapter, RouteTransport]:
    transport = RouteTransport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return StripeCareersAdapter(client), transport


def test_embedded_index_maps_complete_global_inventory_for_downstream_location_filtering() -> None:
    adapter, transport = adapter_for([fixture("search.html")])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 1
    assert [job.external_job_id for job in result.jobs] == ["7118945", "7119000"]
    india, global_job = result.jobs
    assert india.canonical_url == (
        "https://stripe.com/careers/listing/machine-learning-engineer/7118945"
    )
    assert india.location_original == "Bengaluru"
    assert india.location_normalized == ("bengaluru",)
    assert india.published_at is None
    assert india.date_basis is DateBasis.UNKNOWN
    assert india.description is None
    assert india.source_metadata == {
        "adapter_key": STRIPE_CAREERS_ADAPTER_KEY,
        "location_indices": (1,),
        "teams": ("Machine Learning",),
        "tags": ("University",),
        "employment_type": "Full time",
    }
    assert global_job.location_original == "Dublin"
    assert result.diagnostics[-1].category == "publication_date_requires_detail"
    assert transport.calls == [STRIPE_CAREERS_URL]


def test_detail_page_maps_markdown_and_published_date_while_preserving_identity() -> None:
    listing_adapter, _ = adapter_for([fixture("search.html")])
    listed = listing_adapter.list_jobs(source()).jobs[0]
    detail_adapter, transport = adapter_for([fixture("detail.html")])

    detailed = detail_adapter.get_job_detail(source(), listed)

    assert detailed.external_job_id == listed.external_job_id
    assert detailed.canonical_url == listed.canonical_url
    assert detailed.description == (
        "What you'll do\n\n"
        "Build production machine learning systems.\n"
        "Partner with engineers.\n\n"
        "Minimum requirements\n\n"
        "2+ years of software engineering experience."
    )
    assert detailed.description_hash is not None
    assert detailed.published_at == datetime(2026, 9, 28, 9, 57, 35, tzinfo=UTC)
    assert detailed.published_at_raw == "2026-09-28T09:57:35Z"
    assert detailed.date_basis is DateBasis.PUBLISHED
    assert detailed.source_metadata["date_posted"] == "2026-09-28T09:57:35Z"
    assert transport.calls == [listed.canonical_url]


def test_malformed_duplicate_and_invalid_index_fail_closed() -> None:
    page = (FIXTURES / "search.html").read_text(encoding="utf-8")

    malformed_page = page.replace('"locationIndices":[1]', '"locationIndices":[99]', 1)
    malformed, _ = adapter_for([HttpResponse("", "", 200, "text/html", 0, malformed_page.encode())])
    malformed_result = malformed.list_jobs(source())
    assert malformed_result.outcome is AdapterOutcome.FAILED
    assert malformed_result.diagnostics[-1].category == "malformed_job"

    duplicate_page = page.replace("7119000", "7118945")
    duplicate, _ = adapter_for([HttpResponse("", "", 200, "text/html", 0, duplicate_page.encode())])
    duplicate_result = duplicate.list_jobs(source())
    assert duplicate_result.outcome is AdapterOutcome.SUSPICIOUS
    assert duplicate_result.diagnostics[-1].category == "duplicate_job_id"


def test_unapproved_redirect_fails_closed_with_a_diagnostic() -> None:
    response = replace(fixture("search.html"), final_url="https://example.com/careers/search")
    adapter, _ = adapter_for([response])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.FAILED
    assert result.diagnostics[-1].category == "unexpected_redirect"


def test_invalid_source_configuration_is_rejected_before_network() -> None:
    adapter, transport = adapter_for([fixture("search.html")])
    with pytest.raises(AdapterConfigurationError, match="adapter_key=stripe_careers_index"):
        adapter.list_jobs(replace(source(), adapter_parameters={"adapter_key": "other"}))
    with pytest.raises(AdapterConfigurationError, match="requires careers_url"):
        adapter.list_jobs(replace(source(), careers_url="https://stripe.com/jobs/search"))
    assert transport.calls == []
