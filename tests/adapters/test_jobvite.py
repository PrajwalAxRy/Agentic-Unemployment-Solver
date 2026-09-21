"""Fixture-backed tests for Jobvite public careers pages."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
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
from job_finder.adapters.jobvite import JobviteAdapter
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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "jobvite"


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
        company_id="example",
        company_name="Example",
        status=SourceStatus.REVIEWED,
        careers_url="https://example.com/careers/",
        adapter_type=AdapterType.JOBVITE,
        adapter_parameters={"company": "example"},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "datePosted", DateBasis.PUBLISHED, True, "Schema.org detail metadata."
        ),
        detail_strategy=DetailStrategy.DETAIL_PAGE,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=("https://jobs.jobvite.com/example/jobs",),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def fixture(name: str) -> HttpResponse:
    return HttpResponse("", "", 200, "text/html", 0, (FIXTURES / name).read_bytes())


def html_response(value: str) -> HttpResponse:
    return HttpResponse("", "", 200, "text/html", 0, value.encode())


def adapter_for(
    outcomes: list[HttpResponse | HttpRequestError],
) -> tuple[JobviteAdapter, RouteTransport]:
    transport = RouteTransport(outcomes)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return JobviteAdapter(client), transport


def test_complete_board_maps_identity_location_url_and_unknown_listing_date() -> None:
    adapter, transport = adapter_for([fixture("listing.html")])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 1
    assert [job.external_job_id for job in result.jobs] == ["oOne123", "oTwo456"]
    assert result.jobs[0].title_normalized == "machine learning engineer (ai1001)"
    assert result.jobs[0].location_normalized == ("bengaluru", "india")
    assert result.jobs[0].date_basis is DateBasis.UNKNOWN
    assert result.jobs[0].canonical_url == "https://jobs.jobvite.com/example/job/oOne123"
    assert result.diagnostics[-1].category == "missing_publication_date"
    assert transport.calls == ["https://jobs.jobvite.com/example/jobs?nl=1"]


def test_detail_json_ld_supplies_published_date_description_and_location() -> None:
    adapter, transport = adapter_for([fixture("listing.html"), fixture("detail.html")])
    listing = adapter.list_jobs(source()).jobs[0]

    assert isinstance(adapter, JobDetailAdapter)
    detailed = adapter.get_job_detail(source(), listing)

    assert detailed.external_job_id == listing.external_job_id
    assert detailed.canonical_url == listing.canonical_url
    assert detailed.date_basis is DateBasis.PUBLISHED
    assert detailed.published_at == date(2026, 9, 19)
    assert detailed.published_at_raw == "2026-09-19"
    assert detailed.location_original == "Bengaluru, Karnataka, India"
    assert detailed.description == (
        "Build reliable machine-learning services.\n\nPartner with research teams."
    )
    assert detailed.description_hash is not None
    assert transport.calls[-1].endswith("/oOne123?nl=1")


def test_empty_malformed_access_and_request_failure_are_visible() -> None:
    empty, _ = adapter_for([fixture("empty.html")])
    assert empty.list_jobs(source()).outcome is AdapterOutcome.EMPTY

    malformed, _ = adapter_for([fixture("malformed.html")])
    malformed_result = malformed.list_jobs(source())
    assert malformed_result.outcome is AdapterOutcome.FAILED
    assert malformed_result.diagnostics[-1].category == "malformed_job"

    blocked, _ = adapter_for([fixture("access_block.html")])
    assert blocked.list_jobs(source()).outcome is AdapterOutcome.BLOCKED

    failed, _ = adapter_for(
        [HttpRequestError(HttpFailureCategory.TIMEOUT, "request timed out", retryable=True)]
    )
    assert failed.list_jobs(source()).outcome is AdapterOutcome.FAILED


def test_invalid_configuration_duplicates_and_unexpected_pagination_are_rejected() -> None:
    adapter, _ = adapter_for([fixture("listing.html")])
    with pytest.raises(AdapterConfigurationError):
        adapter.list_jobs(replace(source(), adapter_type=AdapterType.ASHBY))
    with pytest.raises(ValueError, match="letters, digits, and hyphens"):
        adapter.list_jobs(replace(source(), adapter_parameters={"company": "bad/company"}))

    listing = (FIXTURES / "listing.html").read_text(encoding="utf-8")
    duplicate_html = listing.replace("oTwo456", "oOne123")
    duplicate, _ = adapter_for([html_response(duplicate_html)])
    assert duplicate.list_jobs(source()).outcome is AdapterOutcome.SUSPICIOUS

    paginated_html = listing.replace(
        "</section>",
        '<nav class="pagination"><a rel="next" href="?page=2">Next</a></nav></section>',
    )
    paginated, _ = adapter_for([html_response(paginated_html)])
    assert paginated.list_jobs(source()).diagnostics[-1].category == "unexpected_pagination"
