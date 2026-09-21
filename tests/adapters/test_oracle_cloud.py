"""Fixture-backed tests for Oracle Cloud Candidate Experience portals."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from job_finder.adapters.base import AdapterConfigurationError, JobDetailAdapter
from job_finder.adapters.http_client import (
    BoundedHttpClient,
    HttpFailureCategory,
    HttpPolicy,
    HttpRequestError,
    HttpResponse,
)
from job_finder.adapters.oracle_cloud import OracleCloudAdapter
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

FIXTURES = Path("tests/fixtures/oracle_cloud")


class RouteTransport:
    def __init__(self, outcomes: list[HttpResponse | HttpRequestError]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, Mapping[str, str]]] = []

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
        max_redirects: int,
    ) -> HttpResponse:
        self.calls.append((url, headers))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, HttpRequestError):
            raise outcome
        return replace(outcome, requested_url=url, final_url=url)


def source() -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id="example",
        company_name="Example",
        status=SourceStatus.REVIEWED,
        careers_url=(
            "https://example.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_TEST/jobs"
        ),
        adapter_type=AdapterType.ORACLE_CLOUD,
        adapter_parameters={"host": "example.fa.oraclecloud.com", "site_number": "CX_TEST"},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy("PostedDate", DateBasis.PUBLISHED, True, "Public posting date."),
        detail_strategy=DetailStrategy.DETAIL_ENDPOINT,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=("https://example.fa.oraclecloud.com",),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def response(body: bytes, *, content_type: str = "application/json") -> HttpResponse:
    return HttpResponse("", "", 200, content_type, 0, body)


def fixture(name: str) -> HttpResponse:
    return response((FIXTURES / name).read_bytes())


def adapter_for(
    outcomes: list[HttpResponse | HttpRequestError],
    *,
    page_size: int = 2,
    max_pages: int = 10,
) -> tuple[OracleCloudAdapter, RouteTransport]:
    transport = RouteTransport(outcomes)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return OracleCloudAdapter(client, page_size=page_size, max_pages=max_pages), transport


def test_count_checked_pagination_maps_identity_locations_url_and_date() -> None:
    adapter, transport = adapter_for([fixture("page_1.json"), fixture("page_2.json")])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 2
    assert [item.external_job_id for item in result.jobs] == ["1001", "1002", "1003"]
    assert result.jobs[0].location_original == (
        "Bengaluru, Karnataka, India | Hyderabad, Telangana, India"
    )
    assert result.jobs[0].location_normalized == (
        "bengaluru",
        "karnataka",
        "india",
        "hyderabad",
        "telangana",
    )
    assert result.jobs[0].canonical_url == (
        "https://example.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_TEST/job/1001"
    )
    assert result.jobs[0].published_at == date(2026, 9, 20)
    assert result.jobs[0].date_basis is DateBasis.PUBLISHED
    first_query = parse_qs(urlsplit(transport.calls[0][0]).query)
    second_query = parse_qs(urlsplit(transport.calls[1][0]).query)
    assert first_query["finder"] == ["findReqs;siteNumber=CX_TEST,limit=2,offset=0"]
    assert second_query["finder"] == ["findReqs;siteNumber=CX_TEST,limit=2,offset=2"]
    assert transport.calls[0][1]["Referer"].endswith("/sites/CX_TEST/jobs")


def test_empty_malformed_access_and_partial_responses_are_visible() -> None:
    empty, _ = adapter_for([fixture("empty.json")])
    assert empty.list_jobs(source()).outcome is AdapterOutcome.EMPTY

    malformed, _ = adapter_for([fixture("malformed.json")])
    malformed_result = malformed.list_jobs(source())
    assert malformed_result.outcome is AdapterOutcome.FAILED
    assert malformed_result.diagnostics[0].category == "malformed_job"

    blocked, _ = adapter_for(
        [response((FIXTURES / "access_block.html").read_bytes(), content_type="text/html")]
    )
    assert blocked.list_jobs(source()).outcome is AdapterOutcome.BLOCKED

    partial, _ = adapter_for(
        [
            fixture("page_1.json"),
            HttpRequestError(HttpFailureCategory.TIMEOUT, "request timed out", retryable=True),
        ]
    )
    assert partial.list_jobs(source()).outcome is AdapterOutcome.PARTIAL


def test_detail_retrieval_preserves_identity_and_adds_description() -> None:
    listing_payload = json.loads((FIXTURES / "page_1.json").read_text(encoding="utf-8"))
    listing_payload["items"][0]["TotalJobsCount"] = 2
    listing_response = response(json.dumps(listing_payload).encode())
    adapter, transport = adapter_for([listing_response, fixture("detail.json")])
    listing = adapter.list_jobs(source()).jobs[0]

    assert isinstance(adapter, JobDetailAdapter)
    detail = adapter.get_job_detail(source(), listing)

    assert detail.external_job_id == listing.external_job_id
    assert detail.canonical_url == listing.canonical_url
    assert detail.published_at == listing.published_at
    assert detail.description == (
        "Build and operate production machine-learning systems.\n\n"
        "Own retrieval and model-serving pipelines.\n\n"
        "Three years of software engineering experience.\n\n"
        "Production ML engineering role."
    )
    assert len(detail.description_hash or "") == 64
    detail_query = parse_qs(urlsplit(transport.calls[1][0]).query)
    assert detail_query["finder"] == ['ById;Id="1001",siteNumber=CX_TEST']
    assert transport.calls[1][1]["Referer"] == listing.canonical_url


def test_inconsistent_total_repeated_page_and_page_limit_are_suspicious() -> None:
    changed = json.loads((FIXTURES / "page_2.json").read_text(encoding="utf-8"))
    changed["items"][0]["TotalJobsCount"] = 4
    inconsistent, _ = adapter_for([fixture("page_1.json"), response(json.dumps(changed).encode())])
    assert inconsistent.list_jobs(source()).diagnostics[-1].category == "inconsistent_total"

    repeated_payload = json.loads((FIXTURES / "page_1.json").read_text(encoding="utf-8"))
    repeated_payload["items"][0]["Offset"] = 2
    repeated, _ = adapter_for(
        [fixture("page_1.json"), response(json.dumps(repeated_payload).encode())]
    )
    assert repeated.list_jobs(source()).diagnostics[-1].category == "repeated_page"

    limited, _ = adapter_for([fixture("page_1.json")], max_pages=1)
    assert limited.list_jobs(source()).diagnostics[-1].category == "pagination_limit"


def test_invalid_source_host_and_detail_identity_are_rejected() -> None:
    adapter, _ = adapter_for([fixture("empty.json")])
    with pytest.raises(AdapterConfigurationError):
        adapter.list_jobs(replace(source(), adapter_type=AdapterType.ASHBY))
    with pytest.raises(ValueError, match="public oraclecloud.com"):
        adapter.list_jobs(
            replace(
                source(),
                adapter_parameters={"host": "example.invalid", "site_number": "CX_TEST"},
            )
        )

    listing_payload = json.loads((FIXTURES / "page_1.json").read_text(encoding="utf-8"))
    listing_payload["items"][0]["TotalJobsCount"] = 2
    detail_payload = json.loads((FIXTURES / "detail.json").read_text(encoding="utf-8"))
    detail_payload["items"][0]["Id"] = "different"
    mismatched, _ = adapter_for(
        [
            response(json.dumps(listing_payload).encode()),
            response(json.dumps(detail_payload).encode()),
        ]
    )
    listing = mismatched.list_jobs(source()).jobs[0]
    with pytest.raises(ValueError, match="does not match"):
        mismatched.get_job_detail(source(), listing)
