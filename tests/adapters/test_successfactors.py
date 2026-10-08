"""Fixture-backed tests for public SuccessFactors RMK career pages."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError, JobDetailAdapter
from job_finder.adapters.http_client import (
    BoundedHttpClient,
    HttpFailureCategory,
    HttpPolicy,
    HttpRequestError,
    HttpResponse,
)
from job_finder.adapters.successfactors import SuccessFactorsAdapter
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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "successfactors"


class RouteTransport:
    def __init__(self, outcomes: list[HttpResponse | HttpRequestError]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    def get(self, url: str, **_: object) -> HttpResponse:
        self.calls.append(url)
        result = self.outcomes.pop(0)
        if isinstance(result, HttpRequestError):
            raise result
        return replace(result, requested_url=url, final_url=url)


def source() -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id="sap",
        company_name="SAP",
        status=SourceStatus.REVIEWED,
        careers_url="https://jobs.sap.com/go/SAP-Jobs-in-India/851201/",
        adapter_type=AdapterType.SUCCESSFACTORS,
        adapter_parameters={
            "host": "jobs.sap.com",
            "category_path": "/go/SAP-Jobs-in-India/851201/",
        },
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "datePosted", DateBasis.PUBLISHED, True, "Schema.org detail metadata."
        ),
        detail_strategy=DetailStrategy.DETAIL_PAGE,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=("https://jobs.sap.com/go/SAP-Jobs-in-India/851201/",),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def fixture(name: str) -> HttpResponse:
    return HttpResponse(
        "",
        "",
        200,
        "text/html",
        0,
        (FIXTURES / name).read_bytes(),
    )


def adapter_for(
    outcomes: list[HttpResponse | HttpRequestError],
    *,
    max_pages: int = 10,
) -> tuple[SuccessFactorsAdapter, RouteTransport]:
    transport = RouteTransport(outcomes)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return SuccessFactorsAdapter(client, page_size=2, max_pages=max_pages), transport


def test_count_checked_pagination_maps_identity_location_url_and_unknown_listing_date() -> None:
    adapter, transport = adapter_for([fixture("page_1.html"), fixture("page_2.html")])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 2
    assert [job.external_job_id for job in result.jobs] == ["1001", "1002", "1003"]
    assert result.jobs[0].title_normalized == "machine learning engineer"
    assert result.jobs[0].location_normalized == ("bengaluru", "in", "560066")
    assert result.jobs[0].date_basis is DateBasis.UNKNOWN
    assert result.jobs[0].canonical_url.endswith("/1001/")
    assert result.diagnostics[-1].category == "missing_publication_date"
    assert "/851201/2/?" in transport.calls[1]


def test_branded_category_prefix_is_preserved_across_pagination() -> None:
    adapter, transport = adapter_for([fixture("page_1.html"), fixture("page_2.html")])
    payu = replace(
        source(),
        company_id="payu",
        company_name="PayU",
        careers_url="https://careers.payu.in/PayU/go/_/514880/",
        adapter_parameters={
            "host": "careers.payu.in",
            "category_path": "/PayU/go/_/514880/",
        },
    )

    result = adapter.list_jobs(payu)

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert "/PayU/go/_/514880/2/?" in transport.calls[1]


def test_detail_page_supplies_published_date_description_and_preserves_identity() -> None:
    adapter, _ = adapter_for(
        [fixture("page_1.html"), fixture("page_2.html"), fixture("detail.html")]
    )
    listing = adapter.list_jobs(source()).jobs[0]

    assert isinstance(adapter, JobDetailAdapter)
    detailed = adapter.get_job_detail(source(), listing)

    assert detailed.external_job_id == listing.external_job_id
    assert detailed.canonical_url == listing.canonical_url
    assert detailed.date_basis is DateBasis.PUBLISHED
    assert detailed.published_at == datetime(2026, 9, 19, 2, tzinfo=UTC)
    assert detailed.published_at_raw == "Sat Sep 19 02:00:00 UTC 2026"
    assert detailed.description == (
        "Build reliable machine-learning services.\n\nPartner with research and platform teams."
    )
    assert detailed.description_hash is not None


def test_detail_without_street_address_falls_back_to_locality_region_country() -> None:
    page = (FIXTURES / "detail.html").read_text(encoding="utf-8")
    streetless = HttpResponse(
        "",
        "",
        200,
        "text/html",
        0,
        re.sub(
            r'<meta[^>]*itemprop="streetAddress"[^>]*>',
            '<meta itemprop="addressLocality" content="Bangalore">'
            '<meta itemprop="addressRegion" content="KA">'
            '<meta itemprop="addressCountry" content="IN">',
            page,
        ).encode(),
    )
    adapter, _ = adapter_for([fixture("page_1.html"), fixture("page_2.html"), streetless])
    listing = adapter.list_jobs(source()).jobs[0]

    detailed = adapter.get_job_detail(source(), listing)

    assert detailed.location_original == "Bangalore, KA, IN"
    assert detailed.description is not None


def test_empty_malformed_access_and_partial_responses_are_visible() -> None:
    empty, _ = adapter_for([fixture("empty.html")])
    assert empty.list_jobs(source()).outcome is AdapterOutcome.EMPTY

    malformed, _ = adapter_for([fixture("malformed.html")])
    malformed_result = malformed.list_jobs(source())
    assert malformed_result.outcome is AdapterOutcome.FAILED
    assert malformed_result.diagnostics[-1].category == "malformed_job"

    blocked, _ = adapter_for([fixture("access_block.html")])
    assert blocked.list_jobs(source()).outcome is AdapterOutcome.BLOCKED

    partial, _ = adapter_for(
        [
            fixture("page_1.html"),
            HttpRequestError(HttpFailureCategory.TIMEOUT, "request timed out", retryable=True),
        ]
    )
    assert partial.list_jobs(source()).outcome is AdapterOutcome.PARTIAL


def test_invalid_configuration_duplicate_identity_and_page_limit_are_rejected() -> None:
    adapter, _ = adapter_for([fixture("empty.html")])
    with pytest.raises(AdapterConfigurationError):
        adapter.list_jobs(replace(source(), adapter_type=AdapterType.ASHBY))
    with pytest.raises(ValueError, match="must match"):
        adapter.list_jobs(
            replace(
                source(),
                adapter_parameters={
                    "host": "example.invalid",
                    "category_path": "/go/SAP-Jobs-in-India/851201/",
                },
            )
        )

    duplicate, _ = adapter_for([fixture("page_1.html"), fixture("page_1.html")])
    assert duplicate.list_jobs(source()).outcome is AdapterOutcome.SUSPICIOUS

    limited, _ = adapter_for([fixture("page_1.html")], max_pages=1)
    assert limited.list_jobs(source()).diagnostics[-1].category == "pagination_limit"
