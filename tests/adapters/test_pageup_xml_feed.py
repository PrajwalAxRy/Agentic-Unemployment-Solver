"""Fixture-backed tests for PageUp public XML job exports."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError
from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy, HttpResponse
from job_finder.adapters.pageup_xml_feed import (
    PAGEUP_XML_ADAPTER_KEY,
    PageUpXmlFeedAdapter,
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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "pageup_xml_feed"
CAREERS_URL = "https://careers.servicenow.com/jobs/"
FEED_URL = "https://careers.servicenow.com/jobs/xml/?rss=true"


class RouteTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **_: object) -> HttpResponse:
        self.calls.append(url)
        return replace(self.responses.pop(0), requested_url=url, final_url=url)


def source() -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id="servicenow",
        company_name="ServiceNow",
        status=SourceStatus.REVIEWED,
        careers_url=CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={
            "adapter_key": PAGEUP_XML_ADAPTER_KEY,
            "feed_url": FEED_URL,
            "publisher": "ServiceNow",
        },
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy("date", DateBasis.PUBLISHED, True, "PageUp feed date."),
        detail_strategy=DetailStrategy.LISTING_PAYLOAD,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(CAREERS_URL, FEED_URL),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def response(body: bytes | None = None) -> HttpResponse:
    return HttpResponse(
        "",
        "",
        200,
        "text/xml",
        0,
        body if body is not None else (FIXTURES / "feed.xml").read_bytes(),
    )


def adapter_for(responses: list[HttpResponse]) -> tuple[PageUpXmlFeedAdapter, RouteTransport]:
    transport = RouteTransport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return PageUpXmlFeedAdapter(client), transport


def test_complete_feed_maps_descriptions_dates_locations_and_identity() -> None:
    adapter, transport = adapter_for([response()])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 1
    assert [job.external_job_id for job in result.jobs] == [
        "744000152129144",
        "744000152000000",
        "8098130",
    ]
    first = result.jobs[0]
    assert first.title_normalized == "machine learning engineer"
    assert first.location_original == "Hyderabad, India"
    assert first.location_normalized == ("hyderabad", "india")
    assert first.published_at == datetime(2026, 9, 28, 9, 57, 35, tzinfo=UTC)
    assert first.date_basis is DateBasis.PUBLISHED
    assert first.canonical_url == (
        "https://careers.servicenow.com/jobs/744000152129144/machine-learning-engineer"
    )
    assert first.description == (
        "What you get to do\n\n"
        "Build production machine learning systems.\n\n"
        "Train and evaluate models.\n\n"
        "Partner with platform engineers."
    )
    assert first.description_hash is not None
    assert first.source_metadata["requisition_id"] == "JB0074545"
    assert first.source_metadata["last_build_at"] == "2026-09-28T05:32:09+00:00"
    assert transport.calls == [FEED_URL]


def test_empty_malformed_duplicate_and_unsafe_xml_fail_closed() -> None:
    feed = (FIXTURES / "feed.xml").read_text(encoding="utf-8")
    empty_feed = feed[: feed.index("  <job>")] + "</source>\n"
    empty, _ = adapter_for([response(empty_feed.encode())])
    empty_result = empty.list_jobs(source())
    assert empty_result.outcome is AdapterOutcome.EMPTY
    assert empty_result.complete is True

    malformed_feed = feed.replace(
        "<apijobid><![CDATA[744000152129144]]></apijobid>",
        "<apijobid><![CDATA[not-numeric]]></apijobid>",
        1,
    )
    malformed, _ = adapter_for([response(malformed_feed.encode())])
    malformed_result = malformed.list_jobs(source())
    assert malformed_result.outcome is AdapterOutcome.FAILED
    assert malformed_result.diagnostics[-1].category == "malformed_job"

    duplicate_feed = feed.replace("744000152000000", "744000152129144")
    duplicate, _ = adapter_for([response(duplicate_feed.encode())])
    duplicate_result = duplicate.list_jobs(source())
    assert duplicate_result.outcome is AdapterOutcome.SUSPICIOUS
    assert duplicate_result.diagnostics[-1].category == "duplicate_job_id"

    unsafe_feed = feed.replace("<source>", '<!DOCTYPE source [<!ENTITY x "unsafe">]>\n<source>', 1)
    unsafe, _ = adapter_for([response(unsafe_feed.encode())])
    unsafe_result = unsafe.list_jobs(source())
    assert unsafe_result.outcome is AdapterOutcome.FAILED
    assert unsafe_result.diagnostics[-1].category == "unsafe_xml"


def test_invalid_source_configuration_is_rejected_before_network() -> None:
    adapter, transport = adapter_for([response()])
    with pytest.raises(AdapterConfigurationError, match="adapter_key=pageup_xml_feed"):
        adapter.list_jobs(
            replace(
                source(),
                adapter_parameters={
                    "adapter_key": "other",
                    "feed_url": FEED_URL,
                    "publisher": "ServiceNow",
                },
            )
        )
    with pytest.raises(AdapterConfigurationError, match="same-host"):
        adapter.list_jobs(
            replace(
                source(),
                adapter_parameters={
                    "adapter_key": PAGEUP_XML_ADAPTER_KEY,
                    "feed_url": "https://example.com/jobs/xml/?rss=true",
                    "publisher": "ServiceNow",
                },
            )
        )
    assert transport.calls == []
