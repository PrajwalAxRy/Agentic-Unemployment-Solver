"""Fixture-backed tests for the Eightfold public candidate API."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError, JobDetailAdapter
from job_finder.adapters.eightfold import EightfoldAdapter
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

FIXTURES = Path("tests/fixtures/eightfold")


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
        careers_url="https://example.eightfold.ai/careers",
        adapter_type=AdapterType.EIGHTFOLD,
        adapter_parameters={"tenant": "example"},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            field_name="t_create",
            basis=DateBasis.UNKNOWN,
            verified_as_publication=False,
            notes="Retained as uncertain evidence pending H5.",
        ),
        detail_strategy=DetailStrategy.DETAIL_ENDPOINT,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=("https://example.eightfold.ai/careers",),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def response(body: bytes, *, content_type: str = "application/json") -> HttpResponse:
    return HttpResponse(
        requested_url="https://example.eightfold.ai/api/apply/v2/jobs?start=0&num=2",
        final_url="https://example.eightfold.ai/api/apply/v2/jobs?start=0&num=2",
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
) -> tuple[EightfoldAdapter, RouteTransport]:
    transport = RouteTransport(outcomes)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return EightfoldAdapter(client, page_size=page_size, max_pages=max_pages), transport


def test_multiple_pages_map_identity_location_url_and_uncertain_date() -> None:
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
    assert result.jobs[0].external_job_id == "755958684099"
    assert result.jobs[0].location_normalized == ("bangalore", "karnataka", "india")
    assert result.jobs[1].location_normalized == ("singapore", "remote")
    assert result.jobs[0].canonical_url == ("https://example.eightfold.ai/careers/job/755958684099")
    assert result.jobs[0].published_at is not None
    assert result.jobs[0].published_at_raw == "1788998400"
    assert result.jobs[0].date_basis is DateBasis.UNKNOWN
    assert result.jobs[0].description is None
    assert {item.category for item in result.diagnostics} == {"unverified_t_create"}
    assert transport.calls[0][0].endswith("jobs?start=0&num=2")
    assert transport.calls[1][0].endswith("jobs?start=2&num=2")
    assert transport.calls[0][1]["Referer"] == "https://example.eightfold.ai/careers"


def test_detail_retrieval_maps_description_and_preserves_identity() -> None:
    first_page = json.loads((FIXTURES / "page_1.json").read_text(encoding="utf-8"))
    first_page["count"] = 2
    adapter, _ = adapter_for(
        [
            response(json.dumps(first_page).encode()),
            response((FIXTURES / "detail.json").read_bytes()),
        ]
    )
    listing = adapter.list_jobs(source()).jobs[0]

    assert isinstance(adapter, JobDetailAdapter)
    detail = adapter.get_job_detail(source(), listing)

    assert detail.external_job_id == listing.external_job_id
    assert detail.canonical_url == listing.canonical_url
    assert detail.description == (
        "Evaluate AI vendor risk and build controls for machine-learning systems."
    )
    assert len(detail.description_hash or "") == 64
    assert detail.source_metadata["display_job_id"] == "REQ-31110"


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
    assert result.diagnostics[0].category == "unsupported_schema"


def test_access_block_html_is_rejected_as_blocked() -> None:
    adapter, _ = adapter_for(
        [response((FIXTURES / "access_block.html").read_bytes(), content_type="text/html")]
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.BLOCKED
    assert result.diagnostics[0].category == "access_block"


def test_repeated_nonempty_page_is_suspicious() -> None:
    page = response((FIXTURES / "page_1.json").read_bytes())
    adapter, _ = adapter_for([page, page])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUSPICIOUS
    assert result.diagnostics[-1].category == "repeated_page"


def test_later_request_failure_returns_partial_jobs() -> None:
    adapter, _ = adapter_for(
        [
            response((FIXTURES / "page_1.json").read_bytes()),
            HttpRequestError(
                HttpFailureCategory.TIMEOUT,
                "request timed out",
                retryable=True,
            ),
        ]
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.PARTIAL
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

    assert transport.calls == []


@pytest.mark.parametrize("tenant", ["example/other", "app"])
def test_invalid_or_shared_tenant_is_rejected_before_network_access(tenant: str) -> None:
    adapter, transport = adapter_for([response((FIXTURES / "empty.json").read_bytes())])
    wrong_source = replace(source(), adapter_parameters={"tenant": tenant})

    with pytest.raises(ValueError):
        adapter.list_jobs(wrong_source)

    assert transport.calls == []
