"""Fixture-backed tests for the Workday public Candidate Experience API."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
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
from job_finder.adapters.workday import WorkdayAdapter
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

FIXTURES = Path("tests/fixtures/workday")


class RouteTransport:
    def __init__(
        self,
        post_outcomes: list[HttpResponse | HttpRequestError],
        *,
        get_outcomes: list[HttpResponse | HttpRequestError] | None = None,
    ) -> None:
        self.post_outcomes = post_outcomes
        self.get_outcomes = get_outcomes or []
        self.post_calls: list[tuple[str, bytes]] = []
        self.get_urls: list[str] = []

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
        max_redirects: int,
    ) -> HttpResponse:
        self.post_calls.append((url, body))
        outcome = self.post_outcomes.pop(0)
        if isinstance(outcome, HttpRequestError):
            raise outcome
        return replace(outcome, requested_url=url, final_url=url)

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
        max_redirects: int,
    ) -> HttpResponse:
        self.get_urls.append(url)
        outcome = self.get_outcomes.pop(0)
        if isinstance(outcome, HttpRequestError):
            raise outcome
        return replace(outcome, requested_url=url, final_url=url)


def source() -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id="example",
        company_name="Example",
        status=SourceStatus.REVIEWED,
        careers_url="https://example.wd1.myworkdayjobs.com/External",
        adapter_type=AdapterType.WORKDAY,
        adapter_parameters={
            "host": "example.wd1.myworkdayjobs.com",
            "tenant": "example",
            "site": "External",
        },
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            field_name="postedOn",
            basis=DateBasis.UNKNOWN,
            verified_as_publication=False,
            notes="Relative Workday labels remain uncertain pending H5.",
        ),
        detail_strategy=DetailStrategy.DETAIL_ENDPOINT,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=("https://example.wd1.myworkdayjobs.com/External",),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def response(body: bytes, *, content_type: str = "application/json") -> HttpResponse:
    return HttpResponse(
        requested_url="https://example.wd1.myworkdayjobs.com/api",
        final_url="https://example.wd1.myworkdayjobs.com/api",
        status_code=200,
        content_type=content_type,
        redirect_count=0,
        body=body,
    )


def adapter_for(
    post_outcomes: list[HttpResponse | HttpRequestError],
    *,
    get_outcomes: list[HttpResponse | HttpRequestError] | None = None,
    page_size: int = 2,
    max_pages: int = 10,
) -> tuple[WorkdayAdapter, RouteTransport]:
    transport = RouteTransport(post_outcomes, get_outcomes=get_outcomes)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return (
        WorkdayAdapter(client, page_size=page_size, max_pages=max_pages),
        transport,
    )


def test_multiple_pages_map_identity_location_url_and_uncertain_date() -> None:
    adapter, transport = adapter_for(
        [
            response((FIXTURES / "healthy_page_1.json").read_bytes()),
            response((FIXTURES / "healthy_page_2.json").read_bytes()),
        ]
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 2
    assert len(result.jobs) == 3
    assert result.jobs[0].external_job_id == "R100"
    assert result.jobs[0].location_normalized == ("bengaluru", "india")
    assert result.jobs[1].location_normalized == ("singapore", "remote")
    assert result.jobs[0].canonical_url == (
        "https://example.wd1.myworkdayjobs.com/External/job/India---Bengaluru/"
        "Software-Engineer--AI-Platform_R100"
    )
    assert result.jobs[0].published_at is None
    assert result.jobs[0].published_at_raw == "Posted 2 Days Ago"
    assert result.jobs[0].date_basis is DateBasis.UNKNOWN
    assert result.jobs[0].description is None
    assert {item.category for item in result.diagnostics} == {"relative_posted_on"}
    assert json.loads(transport.post_calls[0][1])["offset"] == 0
    assert json.loads(transport.post_calls[1][1])["offset"] == 2


def test_later_pages_accept_workdays_zero_total_pagination_shape() -> None:
    second_page = json.loads((FIXTURES / "healthy_page_2.json").read_text(encoding="utf-8"))

    assert second_page["total"] == 0
    adapter, _ = adapter_for(
        [
            response((FIXTURES / "healthy_page_1.json").read_bytes()),
            response(json.dumps(second_page).encode()),
        ]
    )

    assert adapter.list_jobs(source()).outcome is AdapterOutcome.SUCCESS


def test_detail_retrieval_maps_description_and_all_locations() -> None:
    list_payload = json.loads((FIXTURES / "healthy_page_1.json").read_text(encoding="utf-8"))
    list_payload["total"] = 2
    list_response = response(json.dumps(list_payload).encode())
    detail_response = response((FIXTURES / "detail.json").read_bytes())
    adapter, transport = adapter_for(
        [list_response],
        get_outcomes=[detail_response],
        page_size=3,
    )
    listing = adapter.list_jobs(source()).jobs[0]

    assert isinstance(adapter, JobDetailAdapter)
    detail = adapter.get_job_detail(source(), listing)

    assert detail.external_job_id == "R100"
    assert detail.location_normalized == ("india - bengaluru", "singapore", "remote")
    assert detail.description == (
        "Build production machine-learning systems and retrieval pipelines."
    )
    assert len(detail.description_hash or "") == 64
    assert detail.source_metadata["start_date_raw"] == "2026-09-18"
    assert detail.date_basis is DateBasis.UNKNOWN
    assert transport.get_urls == [
        "https://example.wd1.myworkdayjobs.com/wday/cxs/example/External/job/"
        "India---Bengaluru/Software-Engineer--AI-Platform_R100"
    ]


def test_empty_fixture_is_healthy_and_complete() -> None:
    adapter, _ = adapter_for([response((FIXTURES / "empty.json").read_bytes())])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.EMPTY
    assert result.complete is True
    assert result.page_count == 1


def test_malformed_fixture_fails_visibly() -> None:
    adapter, _ = adapter_for([response((FIXTURES / "malformed.json").read_bytes())])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.FAILED
    assert result.complete is False
    assert result.diagnostics[0].category == "unsupported_schema"


def test_missing_listing_location_is_retained_for_detail_retrieval() -> None:
    payload = json.loads((FIXTURES / "healthy_page_1.json").read_text(encoding="utf-8"))
    payload["total"] = 1
    payload["jobPostings"] = [payload["jobPostings"][0]]
    payload["jobPostings"][0]["locationsText"] = None
    adapter, _ = adapter_for([response(json.dumps(payload).encode())])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.jobs[0].location_original == "Location unavailable"
    assert result.jobs[0].source_metadata["listing_location_missing"] is True
    assert {item.category for item in result.diagnostics} == {
        "relative_posted_on",
        "missing_location",
    }


def test_access_block_html_is_rejected_as_blocked() -> None:
    adapter, _ = adapter_for(
        [
            response(
                (FIXTURES / "access_block.html").read_bytes(),
                content_type="text/html",
            )
        ]
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.BLOCKED
    assert result.complete is False
    assert result.diagnostics[0].category == "access_block"


def test_repeated_nonempty_page_is_suspicious() -> None:
    page = response((FIXTURES / "healthy_page_1.json").read_bytes())
    adapter, _ = adapter_for([page, page])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUSPICIOUS
    assert result.complete is False
    assert len(result.jobs) == 2
    assert result.diagnostics[-1].category == "repeated_page"


def test_later_request_failure_returns_partial_jobs() -> None:
    error = HttpRequestError(
        HttpFailureCategory.TIMEOUT,
        "request timed out",
        retryable=True,
    )
    adapter, _ = adapter_for([response((FIXTURES / "healthy_page_1.json").read_bytes()), error])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.PARTIAL
    assert result.complete is False
    assert len(result.jobs) == 2
    assert result.diagnostics[-1].category == "timeout"


def test_pagination_limit_is_suspicious() -> None:
    adapter, _ = adapter_for(
        [response((FIXTURES / "healthy_page_1.json").read_bytes())],
        max_pages=1,
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUSPICIOUS
    assert result.diagnostics[-1].category == "pagination_limit"


def test_invalid_source_fails_before_network_access() -> None:
    adapter, transport = adapter_for([response((FIXTURES / "empty.json").read_bytes())])
    wrong_source = replace(source(), adapter_type=AdapterType.ASHBY)

    with pytest.raises(AdapterConfigurationError, match="cannot handle"):
        adapter.list_jobs(wrong_source)

    assert transport.post_calls == []


def test_mismatched_public_host_is_rejected_before_network_access() -> None:
    adapter, transport = adapter_for([response((FIXTURES / "empty.json").read_bytes())])
    wrong_source = replace(
        source(),
        adapter_parameters={
            "host": "different.wd1.myworkdayjobs.com",
            "tenant": "example",
            "site": "External",
        },
    )

    with pytest.raises(ValueError, match="public jobs host"):
        adapter.list_jobs(wrong_source)

    assert transport.post_calls == []
