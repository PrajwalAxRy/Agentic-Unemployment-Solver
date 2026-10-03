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
    DiagnosticSeverity,
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


@pytest.mark.parametrize(
    "totals",
    [
        (3, 4),
        (4, 3),
    ],
)
def test_active_inventory_total_drift_remains_complete_and_visible(
    totals: tuple[int, int],
) -> None:
    first = json.loads((FIXTURES / "healthy_page_1.json").read_text(encoding="utf-8"))
    second = json.loads((FIXTURES / "healthy_page_2.json").read_text(encoding="utf-8"))
    first["total"] = totals[0]
    if totals[1] == 4:
        extra = dict(second["jobPostings"][0])
        extra["title"] = "AI Platform Engineer"
        extra["externalPath"] = "/job/India---Pune/AI-Platform-Engineer_R103"
        extra["bulletFields"] = ["R103"]
        second["jobPostings"].append(extra)
    second["total"] = totals[1]
    adapter, _ = adapter_for(
        [response(json.dumps(first).encode()), response(json.dumps(second).encode())]
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert len(result.jobs) == totals[1]
    assert "inventory_total_changed" in {diagnostic.category for diagnostic in result.diagnostics}


def test_active_inventory_overlap_retains_each_unique_job_once() -> None:
    first = json.loads((FIXTURES / "healthy_page_1.json").read_text(encoding="utf-8"))
    second = json.loads((FIXTURES / "healthy_page_2.json").read_text(encoding="utf-8"))
    first["total"] = 3
    duplicate = dict(first["jobPostings"][1])
    second["total"] = 4
    second["jobPostings"] = [duplicate, second["jobPostings"][0]]
    adapter, _ = adapter_for(
        [response(json.dumps(first).encode()), response(json.dumps(second).encode())]
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert [job.external_job_id for job in result.jobs] == ["R100", "R101", "R102"]
    diagnostics = {item.category: item for item in result.diagnostics}
    assert diagnostics["inventory_total_changed"].severity is DiagnosticSeverity.WARNING
    assert diagnostics["duplicate_job_id"].severity is DiagnosticSeverity.WARNING


def test_identifier_only_workday_placeholder_is_accounted_without_becoming_a_job() -> None:
    payload = json.loads((FIXTURES / "healthy_page_1.json").read_text(encoding="utf-8"))
    payload["total"] = 3
    payload["jobPostings"].append({"bulletFields": ["JR-PLACEHOLDER"]})
    adapter, _ = adapter_for([response(json.dumps(payload).encode())], page_size=3)

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert len(result.jobs) == 2
    assert "unusable_placeholder" in {diagnostic.category for diagnostic in result.diagnostics}


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


@pytest.mark.parametrize("site_spelling", ["EXTERNAL", "external", "External"])
def test_detail_url_site_is_case_insensitive(site_spelling: str) -> None:
    """Observed live: Bank of America is configured as "lateral-us" but its detail payload's
    externalUrl says "/Lateral-US/job/...". Every detail fetch failed and ~800 listings went
    to review as detail_location_unavailable."""
    list_payload = json.loads((FIXTURES / "healthy_page_1.json").read_text(encoding="utf-8"))
    list_payload["total"] = 1
    list_payload["jobPostings"] = [list_payload["jobPostings"][0]]
    detail_payload = json.loads((FIXTURES / "detail.json").read_text(encoding="utf-8"))
    detail_payload["jobPostingInfo"]["externalUrl"] = (
        f"https://example.wd1.myworkdayjobs.com/{site_spelling}/job/"
        "India---Bengaluru/Software-Engineer--AI-Platform_R100"
    )
    adapter, _ = adapter_for(
        [response(json.dumps(list_payload).encode())],
        get_outcomes=[response(json.dumps(detail_payload).encode())],
    )
    listing = adapter.list_jobs(source()).jobs[0]

    detail = adapter.get_job_detail(source(), listing)

    assert detail.location_normalized == ("india - bengaluru", "singapore", "remote")
    # The stored URL keeps the configured spelling, so it is stable across payloads.
    assert detail.canonical_url == (
        "https://example.wd1.myworkdayjobs.com/External/job/"
        "India---Bengaluru/Software-Engineer--AI-Platform_R100"
    )


def test_detail_url_on_another_board_is_still_rejected() -> None:
    list_payload = json.loads((FIXTURES / "healthy_page_1.json").read_text(encoding="utf-8"))
    list_payload["total"] = 1
    list_payload["jobPostings"] = [list_payload["jobPostings"][0]]
    detail_payload = json.loads((FIXTURES / "detail.json").read_text(encoding="utf-8"))
    detail_payload["jobPostingInfo"]["externalUrl"] = (
        "https://example.wd1.myworkdayjobs.com/Internal/job/Somewhere/Other_R1"
    )
    adapter, _ = adapter_for(
        [response(json.dumps(list_payload).encode())],
        get_outcomes=[response(json.dumps(detail_payload).encode())],
    )
    listing = adapter.list_jobs(source()).jobs[0]

    with pytest.raises(ValueError, match="configured public board"):
        adapter.get_job_detail(source(), listing)


def test_detail_with_no_location_retains_explicit_listing_placeholder() -> None:
    list_payload = json.loads((FIXTURES / "healthy_page_1.json").read_text(encoding="utf-8"))
    list_payload["total"] = 1
    list_payload["jobPostings"] = [list_payload["jobPostings"][0]]
    list_payload["jobPostings"][0]["locationsText"] = None
    detail_payload = json.loads((FIXTURES / "detail.json").read_text(encoding="utf-8"))
    detail_payload["jobPostingInfo"]["location"] = None
    detail_payload["jobPostingInfo"]["additionalLocations"] = []
    adapter, _ = adapter_for(
        [response(json.dumps(list_payload).encode())],
        get_outcomes=[response(json.dumps(detail_payload).encode())],
    )
    listing = adapter.list_jobs(source()).jobs[0]

    detail = adapter.get_job_detail(source(), listing)

    assert detail.location_original == "Location unavailable"
    assert detail.location_normalized == ("location unavailable",)
    assert detail.source_metadata["detail_location_missing"] is True
    assert detail.description is not None


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
