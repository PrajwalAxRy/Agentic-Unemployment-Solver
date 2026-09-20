"""Fixture-backed tests for the Greenhouse public Job Board adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError
from job_finder.adapters.greenhouse import GreenhouseAdapter
from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy, HttpResponse
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

FIXTURES = Path("tests/fixtures/greenhouse")


class FixtureTransport:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.call_count = 0

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
        max_redirects: int,
    ) -> HttpResponse:
        self.call_count += 1
        return replace(self.response, requested_url=url, final_url=url)


def source() -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id="example",
        company_name="Example",
        status=SourceStatus.REVIEWED,
        careers_url="https://job-boards.greenhouse.io/example",
        adapter_type=AdapterType.GREENHOUSE,
        adapter_parameters={"board_token": "example"},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            field_name="first_published",
            basis=DateBasis.PUBLISHED,
            verified_as_publication=True,
            notes="Verified against Greenhouse's public Job Board API documentation.",
        ),
        detail_strategy=DetailStrategy.LISTING_PAYLOAD,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=("https://docs.greenhouse.io/job-board.html",),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def adapter_for(
    body: bytes,
    *,
    content_type: str = "application/json",
) -> tuple[GreenhouseAdapter, FixtureTransport]:
    response = HttpResponse(
        requested_url="https://boards-api.greenhouse.io/v1/boards/example/jobs?content=true",
        final_url="https://boards-api.greenhouse.io/v1/boards/example/jobs?content=true",
        status_code=200,
        content_type=content_type,
        redirect_count=0,
        body=body,
    )
    transport = FixtureTransport(response)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return GreenhouseAdapter(client), transport


def test_healthy_fixture_maps_published_and_update_date_evidence() -> None:
    adapter, _ = adapter_for((FIXTURES / "healthy.json").read_bytes())

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert len(result.jobs) == 2
    assert result.jobs[0].external_job_id == "4724189005"
    assert result.jobs[0].date_basis is DateBasis.PUBLISHED
    assert result.jobs[0].description == "Build evaluation datasets for production AI systems."
    assert result.jobs[0].canonical_url.endswith("/4724189005")
    assert result.jobs[1].date_basis is DateBasis.UPDATED
    assert result.jobs[1].location_normalized == ("singapore", "remote")
    assert result.jobs[1].canonical_url.endswith("?gh_jid=8123456002")
    assert result.diagnostics[0].category == "updated_date_fallback"


def test_empty_fixture_is_healthy_and_complete() -> None:
    adapter, _ = adapter_for((FIXTURES / "empty.json").read_bytes())

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.EMPTY
    assert result.complete is True
    assert result.page_count == 1


def test_malformed_fixture_fails_visibly() -> None:
    adapter, _ = adapter_for((FIXTURES / "malformed.json").read_bytes())

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.FAILED
    assert result.complete is False
    assert result.diagnostics[0].category == "malformed_job"


def test_inconsistent_meta_total_is_suspicious_not_complete() -> None:
    adapter, _ = adapter_for((FIXTURES / "incomplete.json").read_bytes())

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUSPICIOUS
    assert result.complete is False
    assert result.diagnostics[-1].category == "incomplete_collection"


def test_access_block_html_is_rejected_as_blocked() -> None:
    body = Path("tests/fixtures/ashby/access_block.html").read_bytes()
    adapter, _ = adapter_for(body, content_type="text/html")

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.BLOCKED
    assert result.diagnostics[0].category == "access_block"


def test_duplicate_ids_are_suspicious() -> None:
    payload = json.loads((FIXTURES / "healthy.json").read_text(encoding="utf-8"))
    payload["jobs"].append(payload["jobs"][0])
    payload["meta"]["total"] = 3
    adapter, _ = adapter_for(json.dumps(payload).encode())

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUSPICIOUS
    assert len(result.jobs) == 2
    assert result.diagnostics[-1].category == "duplicate_job_id"


def test_invalid_source_fails_before_network_access() -> None:
    adapter, transport = adapter_for((FIXTURES / "healthy.json").read_bytes())
    wrong_source = replace(source(), adapter_type=AdapterType.ASHBY)

    with pytest.raises(AdapterConfigurationError, match="cannot handle"):
        adapter.list_jobs(wrong_source)

    assert transport.call_count == 0
