"""Fixture-backed tests for the Lever public Postings API adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError
from job_finder.adapters.http_client import (
    BoundedHttpClient,
    HttpFailureCategory,
    HttpPolicy,
    HttpRequestError,
    HttpResponse,
)
from job_finder.adapters.lever import LeverAdapter
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

FIXTURES = Path("tests/fixtures/lever")


class RouteTransport:
    def __init__(self, outcomes: list[HttpResponse | HttpRequestError]) -> None:
        self.outcomes = outcomes
        self.urls: list[str] = []

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
        max_redirects: int,
    ) -> HttpResponse:
        self.urls.append(url)
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
        careers_url="https://jobs.lever.co/example",
        adapter_type=AdapterType.LEVER,
        adapter_parameters={"site": "example"},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            field_name="createdAt",
            basis=DateBasis.UNKNOWN,
            verified_as_publication=False,
            notes="Lever createdAt is retained but is not verified as publication time.",
        ),
        detail_strategy=DetailStrategy.LISTING_PAYLOAD,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=("https://github.com/lever/postings-api",),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def response(body: bytes, *, content_type: str = "application/json") -> HttpResponse:
    return HttpResponse(
        requested_url="https://api.lever.co/v0/postings/example",
        final_url="https://api.lever.co/v0/postings/example",
        status_code=200,
        content_type=content_type,
        redirect_count=0,
        body=body,
    )


def adapter_for(
    outcomes: list[HttpResponse | HttpRequestError],
    *,
    page_size: int = 2,
    max_pages: int = 10,
) -> tuple[LeverAdapter, RouteTransport]:
    transport = RouteTransport(outcomes)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return (
        LeverAdapter(client, page_size=page_size, max_pages=max_pages),
        transport,
    )


def test_multiple_pages_map_identity_description_location_url_and_uncertain_date() -> None:
    adapter, transport = adapter_for(
        [
            response((FIXTURES / "page_1.json").read_bytes()),
            response((FIXTURES / "page_2.json").read_bytes()),
        ]
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 2
    assert len(result.jobs) == 3
    assert result.jobs[0].external_job_id == "6a0f0b5a-55a8-4f42-8798-9cc840b04f15"
    assert result.jobs[0].description.startswith("Build LLM evaluation")
    assert result.jobs[0].location_normalized == ("singapore", "remote")
    assert result.jobs[0].canonical_url.endswith("6a0f0b5a-55a8-4f42-8798-9cc840b04f15")
    assert result.jobs[0].published_at is not None
    assert result.jobs[0].date_basis is DateBasis.UNKNOWN
    assert {item.category for item in result.diagnostics} == {"unverified_created_at"}
    assert "skip=0&limit=2" in transport.urls[0]
    assert "skip=2&limit=2" in transport.urls[1]


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
    assert result.diagnostics[0].category == "malformed_job"


def test_html_description_is_used_when_plain_description_is_empty() -> None:
    adapter, _ = adapter_for([response((FIXTURES / "html_description_fallback.json").read_bytes())])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.jobs[0].description == (
        "Lead an engineering team building production AI services. Coach engineers."
    )


def test_structured_lists_complete_the_description() -> None:
    adapter, _ = adapter_for([response((FIXTURES / "lists_only_description.json").read_bytes())])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.jobs[0].description == (
        "Responsibilities: Build automated test systems. Validate model-backed features. "
        "Requirements: Python test automation experience."
    )


def test_missing_description_is_retained_with_explicit_diagnostic() -> None:
    adapter, _ = adapter_for([response((FIXTURES / "missing_description.json").read_bytes())])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.jobs[0].description is None
    assert result.jobs[0].description_hash is None
    assert {item.category for item in result.diagnostics} == {
        "unverified_created_at",
        "missing_description",
    }


def test_access_block_html_is_rejected_as_blocked() -> None:
    body = Path("tests/fixtures/ashby/access_block.html").read_bytes()
    adapter, _ = adapter_for([response(body, content_type="text/html")])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.BLOCKED
    assert result.complete is False
    assert result.diagnostics[0].category == "access_block"


def test_repeated_nonempty_page_is_suspicious() -> None:
    page = response((FIXTURES / "page_1.json").read_bytes())
    adapter, _ = adapter_for([page, page])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUSPICIOUS
    assert result.complete is False
    assert len(result.jobs) == 2
    assert result.diagnostics[-1].category == "repeated_page"


def test_duplicate_id_across_pages_is_suspicious() -> None:
    first = response((FIXTURES / "page_1.json").read_bytes())
    jobs = json.loads((FIXTURES / "page_1.json").read_text(encoding="utf-8"))
    duplicate = response(json.dumps([jobs[0]]).encode())
    adapter, _ = adapter_for([first, duplicate])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUSPICIOUS
    assert result.complete is False
    assert result.diagnostics[-1].category == "duplicate_job_id"


def test_later_request_failure_returns_partial_jobs() -> None:
    error = HttpRequestError(
        HttpFailureCategory.TIMEOUT,
        "request timed out",
        retryable=True,
    )
    adapter, _ = adapter_for([response((FIXTURES / "page_1.json").read_bytes()), error])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.PARTIAL
    assert result.complete is False
    assert len(result.jobs) == 2
    assert result.diagnostics[-1].category == "timeout"


def test_pagination_limit_is_suspicious() -> None:
    adapter, _ = adapter_for(
        [response((FIXTURES / "page_1.json").read_bytes())],
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

    assert transport.urls == []
