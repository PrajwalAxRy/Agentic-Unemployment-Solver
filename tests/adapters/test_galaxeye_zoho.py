"""Fixture-backed tests for GalaxEye's official Zoho Recruit RSS source."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError
from job_finder.adapters.galaxeye_zoho import (
    GALAXEYE_ADAPTER_KEY,
    GALAXEYE_CAREERS_URL,
    GALAXEYE_RSS_URL,
    GalaxEyeZohoAdapter,
)
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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "galaxeye_zoho"


class RouteTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **_: object) -> HttpResponse:
        self.calls.append(url)
        response = self.responses.pop(0)
        return replace(response, requested_url=url, final_url=response.final_url or url)


def source() -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id="galaxeye",
        company_name="GalaxEye",
        status=SourceStatus.REVIEWED,
        careers_url=GALAXEYE_CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": GALAXEYE_ADAPTER_KEY},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy("pubDate", DateBasis.PUBLISHED, True, "Official RSS date."),
        detail_strategy=DetailStrategy.DETAIL_PAGE,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(GALAXEYE_CAREERS_URL, GALAXEYE_RSS_URL),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def response(body: bytes, *, content_type: str, final_url: str = "") -> HttpResponse:
    return HttpResponse("", final_url, 200, content_type, 0, body)


def adapter_for(responses: list[HttpResponse]) -> tuple[GalaxEyeZohoAdapter, RouteTransport]:
    transport = RouteTransport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return GalaxEyeZohoAdapter(client), transport


def feed_response(body: bytes | None = None, *, final_url: str = "") -> HttpResponse:
    return response(
        body if body is not None else (FIXTURES / "careers.xml").read_bytes(),
        content_type="application/rss+xml",
        final_url=final_url,
    )


def test_rss_maps_complete_identity_location_dates_and_descriptions() -> None:
    adapter, transport = adapter_for([feed_response()])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 1
    assert [job.external_job_id for job in result.jobs] == [
        "214465000000581913",
        "214465000003821743",
    ]
    first = result.jobs[0]
    assert first.title_original == "AI Researcher"
    assert first.location_original == "Bangalore North Karnataka India"
    assert first.published_at is not None
    assert first.published_at.isoformat() == "2026-02-25"
    assert first.date_basis is DateBasis.PUBLISHED
    assert first.description is not None
    assert "satellite foundation models" in first.description
    assert first.description_hash is not None
    assert first.source_metadata["category"] == "AI Research"
    assert transport.calls == [GALAXEYE_RSS_URL]


def test_feed_identity_duplicates_schema_and_redirect_fail_closed() -> None:
    page = (FIXTURES / "careers.xml").read_text(encoding="utf-8")
    mismatch, _ = adapter_for(
        [feed_response(page.replace("214465000000581913</guid>", "999</guid>").encode())]
    )
    assert mismatch.list_jobs(source()).outcome is AdapterOutcome.FAILED

    duplicate_page = page.replace(
        "214465000003821743/Backend-Engineer-ML-systems",
        "214465000000581913/Backend-Engineer-ML-systems",
    ).replace("214465000003821743</guid>", "214465000000581913</guid>")
    duplicate, _ = adapter_for([feed_response(duplicate_page.encode())])
    assert duplicate.list_jobs(source()).outcome is AdapterOutcome.SUSPICIOUS

    doctype, _ = adapter_for([feed_response(b"<!DOCTYPE rss><rss></rss>")])
    assert doctype.list_jobs(source()).outcome is AdapterOutcome.FAILED

    redirected, _ = adapter_for([feed_response(final_url="https://example.com/jobs.xml")])
    assert redirected.list_jobs(source()).outcome is AdapterOutcome.FAILED


def test_source_configuration_is_strict() -> None:
    configured, transport = adapter_for([])
    with pytest.raises(AdapterConfigurationError, match="adapter_key=galaxeye_zoho_rss"):
        configured.list_jobs(replace(source(), adapter_parameters={"adapter_key": "other"}))
    with pytest.raises(AdapterConfigurationError, match="requires careers_url"):
        configured.list_jobs(replace(source(), careers_url="https://galaxeye.space/job-portal"))
    assert transport.calls == []
