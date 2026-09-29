"""Fixture-backed tests for Index Exchange's official careers inventory."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError
from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy, HttpResponse
from job_finder.adapters.index_exchange import (
    INDEX_EXCHANGE_ADAPTER_KEY,
    INDEX_EXCHANGE_CAREERS_URL,
    IndexExchangeCareersAdapter,
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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "index_exchange"


class RouteTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **_: object) -> HttpResponse:
        self.calls.append(url)
        response = self.responses.pop(0)
        return replace(response, requested_url=url, final_url=response.final_url or url)

    def post(self, url: str, **_: object) -> HttpResponse:
        return self.get(url)


def source() -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id="index-exchange",
        company_name="Index Exchange",
        status=SourceStatus.REVIEWED,
        careers_url=INDEX_EXCHANGE_CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": INDEX_EXCHANGE_ADAPTER_KEY},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(None, DateBasis.UNKNOWN, False, "No public listing date."),
        detail_strategy=DetailStrategy.DETAIL_PAGE,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(INDEX_EXCHANGE_CAREERS_URL,),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def response(name: str, *, final_url: str = "") -> HttpResponse:
    body = (FIXTURES / name).read_bytes()
    return HttpResponse("", final_url, 200, "text/html", 0, body)


def adapter_for(
    responses: list[HttpResponse],
) -> tuple[IndexExchangeCareersAdapter, RouteTransport]:
    transport = RouteTransport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return IndexExchangeCareersAdapter(client), transport


def test_complete_inventory_collapses_multilocation_rows_and_retrieves_detail() -> None:
    adapter, transport = adapter_for([response("listing.html"), response("detail.html")])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 1
    assert len(result.jobs) == 2
    first, second = result.jobs
    assert first.external_job_id == "job-one"
    assert first.location_normalized == ("bengaluru",)
    assert second.location_original == "Toronto | New York"
    assert second.location_normalized == ("toronto", "new york")
    assert first.date_basis is DateBasis.UNKNOWN
    assert first.published_at is None

    detail = adapter.get_job_detail(source(), first)
    assert detail.description is not None
    assert "distributed platform" in detail.description
    assert detail.description_hash is not None
    assert transport.calls == [INDEX_EXCHANGE_CAREERS_URL, first.canonical_url]


def test_count_mismatch_conflicting_duplicate_and_redirect_fail_closed() -> None:
    mismatch = (
        (FIXTURES / "listing.html")
        .read_text(encoding="utf-8")
        .replace('data-count="3"', 'data-count="4"')
    )
    adapter, _ = adapter_for(
        [HttpResponse("", INDEX_EXCHANGE_CAREERS_URL, 200, "text/html", 0, mismatch.encode())]
    )
    assert adapter.list_jobs(source()).outcome is AdapterOutcome.FAILED

    conflict = (
        (FIXTURES / "listing.html")
        .read_text(encoding="utf-8")
        .replace(
            'data-list-item-title="Platform Engineer" data-list-item-location="New York"',
            'data-list-item-title="Different Role" data-list-item-location="New York"',
            1,
        )
    )
    adapter, _ = adapter_for(
        [HttpResponse("", INDEX_EXCHANGE_CAREERS_URL, 200, "text/html", 0, conflict.encode())]
    )
    assert adapter.list_jobs(source()).outcome is AdapterOutcome.FAILED

    adapter, _ = adapter_for([response("listing.html", final_url="https://example.com/jobs")])
    assert adapter.list_jobs(source()).outcome is AdapterOutcome.FAILED


def test_detail_identity_and_configuration_are_strict() -> None:
    listing, _ = adapter_for([response("listing.html")])
    job = listing.list_jobs(source()).jobs[0]
    broken_html = (
        (FIXTURES / "detail.html")
        .read_text(encoding="utf-8")
        .replace("Staff Engineer", "Different title")
    )
    adapter, _ = adapter_for(
        [HttpResponse("", job.canonical_url, 200, "text/html", 0, broken_html.encode())]
    )
    with pytest.raises(ValueError, match="title did not match"):
        adapter.get_job_detail(source(), job)

    configured, transport = adapter_for([])
    with pytest.raises(
        AdapterConfigurationError, match="adapter_key=index_exchange_official_inventory"
    ):
        configured.list_jobs(replace(source(), adapter_parameters={"adapter_key": "other"}))
    with pytest.raises(AdapterConfigurationError, match="approved careers URL"):
        configured.list_jobs(replace(source(), careers_url="https://example.com/careers"))
    assert transport.calls == []
