"""Fixture-backed tests for Atomicwork's custom Webflow adapter."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.atomicwork import (
    ATOMICWORK_CAREERS_URL,
    ATOMICWORK_SITEMAP_URL,
    AtomicworkWebflowAdapter,
)
from job_finder.adapters.base import AdapterConfigurationError, JobDetailAdapter
from job_finder.adapters.http_client import (
    BoundedHttpClient,
    HttpFailureCategory,
    HttpPolicy,
    HttpRequestError,
    HttpResponse,
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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "atomicwork"


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
        company_id="atomicwork",
        company_name="Atomicwork",
        status=SourceStatus.REVIEWED,
        careers_url=ATOMICWORK_CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": "atomicwork_webflow"},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(None, DateBasis.UNKNOWN, False, "No public date field."),
        detail_strategy=DetailStrategy.DETAIL_PAGE,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(ATOMICWORK_CAREERS_URL, ATOMICWORK_SITEMAP_URL),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def fixture(name: str, content_type: str) -> HttpResponse:
    return HttpResponse("", "", 200, content_type, 0, (FIXTURES / name).read_bytes())


def adapter_for(
    outcomes: list[HttpResponse | HttpRequestError],
) -> tuple[AtomicworkWebflowAdapter, RouteTransport]:
    transport = RouteTransport(outcomes)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return AtomicworkWebflowAdapter(client), transport


def healthy_responses() -> list[HttpResponse | HttpRequestError]:
    return [
        fixture("healthy.html", "text/html"),
        fixture("healthy_sitemap.xml", "application/rss+xml"),
    ]


def test_listing_reconciles_sitemap_and_maps_path_identity_with_unknown_dates() -> None:
    adapter, transport = adapter_for(healthy_responses())

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 2
    assert [job.external_job_id for job in result.jobs] == ["4080659008", "4062696008"]
    assert result.jobs[0].title_normalized == "product manager - platform"
    assert result.jobs[1].location_normalized == ("bengaluru", "india")
    assert all(job.date_basis is DateBasis.UNKNOWN for job in result.jobs)
    assert all(job.published_at is None for job in result.jobs)
    assert result.jobs[1].canonical_url == "https://www.atomicwork.com/careers/4062696008"
    assert result.jobs[1].source_metadata["department"] == "Backend Engineering"
    assert result.diagnostics[-1].category == "missing_publication_date"
    assert transport.calls == [ATOMICWORK_CAREERS_URL, ATOMICWORK_SITEMAP_URL]


def test_detail_supplies_description_and_keeps_unknown_date() -> None:
    adapter, transport = adapter_for(healthy_responses() + [fixture("detail.html", "text/html")])
    listing = adapter.list_jobs(source()).jobs[1]

    assert isinstance(adapter, JobDetailAdapter)
    detailed = adapter.get_job_detail(source(), listing)

    assert detailed.external_job_id == listing.external_job_id
    assert detailed.canonical_url == listing.canonical_url
    assert detailed.location_original == "Bengaluru, India"
    assert detailed.date_basis is DateBasis.UNKNOWN
    assert detailed.published_at is None
    assert detailed.description == (
        "Build reliable AI-enabled service-management systems.\n\n"
        "What you'll do\n\n"
        "Design and operate backend services.\n\n"
        "Partner with product and engineering teams."
    )
    assert detailed.description_hash is not None
    assert detailed.source_metadata["detail_department"] == "Backend Engineering"
    assert detailed.source_metadata["application_url"] == (
        "https://job-boards.greenhouse.io/atomicwork/jobs/4143684008"
    )
    assert transport.calls[-1] == listing.canonical_url


def test_explicit_empty_board_requires_empty_sitemap() -> None:
    adapter, _ = adapter_for(
        [
            fixture("empty.html", "text/html"),
            fixture("empty_sitemap.xml", "application/rss+xml"),
        ]
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.EMPTY
    assert result.complete is True
    assert result.page_count == 2


@pytest.mark.parametrize(
    ("listing_fixture", "expected_outcome", "expected_category"),
    [
        ("malformed.html", AdapterOutcome.FAILED, "malformed_job"),
        ("duplicate.html", AdapterOutcome.SUSPICIOUS, "duplicate_job_id"),
        ("off_origin.html", AdapterOutcome.FAILED, "malformed_job"),
    ],
)
def test_malformed_duplicate_and_off_origin_rows_fail_visibly(
    listing_fixture: str,
    expected_outcome: AdapterOutcome,
    expected_category: str,
) -> None:
    adapter, _ = adapter_for([fixture(listing_fixture, "text/html")])

    result = adapter.list_jobs(source())

    assert result.outcome is expected_outcome
    assert result.complete is False
    assert result.diagnostics[-1].category == expected_category


def test_listing_sitemap_disagreement_is_suspicious() -> None:
    mismatched = (
        (FIXTURES / "healthy_sitemap.xml")
        .read_text(encoding="utf-8")
        .replace(
            "  <url><loc>https://www.atomicwork.com/careers/4080659008</loc></url>\n",
            "",
        )
    )
    adapter, _ = adapter_for(
        [
            fixture("healthy.html", "text/html"),
            HttpResponse("", "", 200, "application/rss+xml", 0, mismatched.encode()),
        ]
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUSPICIOUS
    assert result.diagnostics[-1].category == "listing_sitemap_mismatch"
    assert result.diagnostics[-1].context == {
        "listing_count": "2",
        "sitemap_count": "1",
        "listing_only": "1",
        "sitemap_only": "0",
    }


def test_configuration_and_request_failures_are_rejected() -> None:
    adapter, _ = adapter_for(healthy_responses())
    with pytest.raises(AdapterConfigurationError, match="adapter_key=atomicwork_webflow"):
        adapter.list_jobs(replace(source(), adapter_parameters={"adapter_key": "other"}))
    with pytest.raises(AdapterConfigurationError, match="requires careers_url"):
        adapter.list_jobs(replace(source(), careers_url="https://www.atomicwork.com/careers"))

    failed, _ = adapter_for(
        [HttpRequestError(HttpFailureCategory.TIMEOUT, "request timed out", retryable=True)]
    )
    result = failed.list_jobs(source())
    assert result.outcome is AdapterOutcome.FAILED
    assert result.diagnostics[-1].category == "timeout"
