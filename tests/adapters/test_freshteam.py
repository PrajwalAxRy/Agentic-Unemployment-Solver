"""Fixture-backed tests for Freshteam public career portals."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError, JobDetailAdapter
from job_finder.adapters.freshteam import FreshteamAdapter
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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "freshteam"


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
        careers_url="https://example.freshteam.com/jobs",
        adapter_type=AdapterType.FRESHTEAM,
        adapter_parameters={"account": "example"},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "datePosted", DateBasis.PUBLISHED, True, "Schema.org detail metadata."
        ),
        detail_strategy=DetailStrategy.DETAIL_PAGE,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=("https://example.freshteam.com/jobs",),
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
) -> tuple[FreshteamAdapter, RouteTransport]:
    transport = RouteTransport(outcomes)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return FreshteamAdapter(client), transport


def test_complete_board_maps_declared_count_identity_location_and_remote() -> None:
    adapter, transport = adapter_for([fixture("listing.html")])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 1
    assert [job.external_job_id for job in result.jobs] == ["QBdFZljpx03q", "68V3608ei65Q"]
    assert result.jobs[0].title_normalized == "software development engineer - 3"
    assert result.jobs[0].location_normalized == ("bengaluru", "india")
    assert result.jobs[1].location_normalized == ("remote", "india")
    assert result.jobs[1].source_metadata["remote"] is True
    assert result.jobs[0].date_basis is DateBasis.UNKNOWN
    assert result.jobs[0].canonical_url == (
        "https://example.freshteam.com/jobs/QBdFZljpx03q/software-development-engineer-3"
    )
    assert transport.calls == ["https://example.freshteam.com/jobs"]


def test_detail_json_ld_supplies_timestamp_description_and_location() -> None:
    adapter, transport = adapter_for([fixture("listing.html"), fixture("detail.html")])
    listing = adapter.list_jobs(source()).jobs[0]

    assert isinstance(adapter, JobDetailAdapter)
    detailed = adapter.get_job_detail(source(), listing)

    assert detailed.external_job_id == listing.external_job_id
    assert detailed.canonical_url == listing.canonical_url
    assert detailed.date_basis is DateBasis.PUBLISHED
    assert detailed.published_at == datetime(2026, 9, 27, 16, 52, 34, tzinfo=UTC)
    assert detailed.published_at_raw == "2026-09-27 16:52:34 UTC"
    assert detailed.location_original == "Bengaluru, India"
    assert detailed.description == "Build reliable AI services.\n\nPartner with research teams."
    assert detailed.description_hash is not None
    assert transport.calls[-1].endswith("/QBdFZljpx03q/software-development-engineer-3")


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


def test_invalid_configuration_duplicates_and_count_mismatch_are_rejected() -> None:
    adapter, _ = adapter_for([fixture("listing.html")])
    with pytest.raises(AdapterConfigurationError):
        adapter.list_jobs(replace(source(), adapter_type=AdapterType.ASHBY))
    with pytest.raises(ValueError, match="letters, digits, and hyphens"):
        adapter.list_jobs(replace(source(), adapter_parameters={"account": "bad/account"}))

    listing = (FIXTURES / "listing.html").read_text(encoding="utf-8")
    duplicate_html = listing.replace("68V3608ei65Q", "QBdFZljpx03q")
    duplicate, _ = adapter_for([html_response(duplicate_html)])
    assert duplicate.list_jobs(source()).diagnostics[-1].category == "duplicate_job_id"

    mismatched_html = listing.replace("#2 Jobs", "#3 Jobs")
    mismatched, _ = adapter_for([html_response(mismatched_html)])
    result = mismatched.list_jobs(source())
    assert result.outcome is AdapterOutcome.SUSPICIOUS
    assert result.diagnostics[-1].category == "declared_count_mismatch"
