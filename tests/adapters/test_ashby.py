"""Fixture-backed tests for the Ashby public posting adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.ashby import AshbyAdapter
from job_finder.adapters.base import AdapterConfigurationError
from job_finder.adapters.http_client import (
    BoundedHttpClient,
    HttpPolicy,
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

FIXTURES = Path("tests/fixtures/ashby")


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
        careers_url="https://jobs.ashbyhq.com/example",
        adapter_type=AdapterType.ASHBY,
        adapter_parameters={"board_name": "example"},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            field_name="publishedAt",
            basis=DateBasis.PUBLISHED,
            verified_as_publication=True,
            notes="Verified against Ashby's public job-posting API documentation.",
        ),
        detail_strategy=DetailStrategy.LISTING_PAYLOAD,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=("https://developers.ashbyhq.com/docs/public-job-posting-api",),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def adapter_for(
    body: bytes,
    *,
    content_type: str = "application/json",
) -> tuple[AshbyAdapter, FixtureTransport]:
    response = HttpResponse(
        requested_url="https://api.ashbyhq.com/posting-api/job-board/example",
        final_url="https://api.ashbyhq.com/posting-api/job-board/example",
        status_code=200,
        content_type=content_type,
        redirect_count=0,
        body=body,
    )
    transport = FixtureTransport(response)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return AshbyAdapter(client), transport


def test_healthy_fixture_maps_complete_normalized_jobs() -> None:
    adapter, _ = adapter_for((FIXTURES / "healthy.json").read_bytes())

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 1
    assert len(result.jobs) == 2
    assert result.jobs[0].external_job_id == "a3c5bd4c-f6fb-4eb0-b943-e0e1a1d878c5"
    assert result.jobs[0].title_normalized == "software engineer intern (ai-native)"
    assert result.jobs[0].date_basis is DateBasis.PUBLISHED
    assert result.jobs[0].published_at is not None
    assert len(result.jobs[0].description_hash or "") == 64
    assert result.jobs[1].location_normalized == (
        "bengaluru",
        "india",
        "singapore",
        "remote",
    )


def test_empty_fixture_is_healthy_and_complete() -> None:
    adapter, _ = adapter_for((FIXTURES / "empty.json").read_bytes())

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.EMPTY
    assert result.complete is True
    assert result.jobs == ()
    assert result.page_count == 1


def test_malformed_fixture_fails_with_field_diagnostic() -> None:
    adapter, _ = adapter_for((FIXTURES / "malformed.json").read_bytes())

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.FAILED
    assert result.complete is False
    assert result.diagnostics[0].category == "malformed_job"
    assert "title" in result.diagnostics[0].message


def test_access_block_fixture_is_rejected_as_blocked() -> None:
    adapter, _ = adapter_for(
        (FIXTURES / "access_block.html").read_bytes(),
        content_type="text/html",
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.BLOCKED
    assert result.complete is False
    assert result.diagnostics[0].category == "access_block"


def test_duplicate_ids_are_suspicious_and_not_emitted_twice() -> None:
    payload = json.loads((FIXTURES / "healthy.json").read_text(encoding="utf-8"))
    payload["jobs"].append(payload["jobs"][0])
    adapter, _ = adapter_for(json.dumps(payload).encode())

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUSPICIOUS
    assert result.complete is False
    assert len(result.jobs) == 2
    assert result.diagnostics[-1].category == "duplicate_job_id"


def test_canonical_url_strips_tracking_query_and_fragment() -> None:
    payload = json.loads((FIXTURES / "healthy.json").read_text(encoding="utf-8"))
    payload["jobs"] = [payload["jobs"][0]]
    payload["jobs"][0]["jobUrl"] += "/?utm_source=test#apply"
    adapter, _ = adapter_for(json.dumps(payload).encode())

    result = adapter.list_jobs(source())

    assert result.jobs[0].canonical_url.endswith("a3c5bd4c-f6fb-4eb0-b943-e0e1a1d878c5")
    assert "?" not in result.jobs[0].canonical_url
    assert "#" not in result.jobs[0].canonical_url


def test_invalid_source_configuration_fails_before_network_access() -> None:
    adapter, transport = adapter_for((FIXTURES / "healthy.json").read_bytes())
    wrong_source = replace(source(), adapter_type=AdapterType.GREENHOUSE)

    with pytest.raises(AdapterConfigurationError, match="cannot handle"):
        adapter.list_jobs(wrong_source)

    assert transport.call_count == 0
