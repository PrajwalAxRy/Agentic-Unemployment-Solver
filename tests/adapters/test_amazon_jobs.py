"""Fixture-backed tests for Amazon Jobs' public India search."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from job_finder.adapters.amazon_jobs import (
    AMAZON_JOBS_ADAPTER_KEY,
    AMAZON_JOBS_CAREERS_URL,
    AmazonJobsAdapter,
)
from job_finder.adapters.base import AdapterConfigurationError
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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "amazon_jobs"


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
        company_id="amazon-aws",
        company_name="Amazon / AWS",
        status=SourceStatus.REVIEWED,
        careers_url=AMAZON_JOBS_CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": AMAZON_JOBS_ADAPTER_KEY},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "posted_date", DateBasis.PUBLISHED, True, "Amazon Jobs publication date."
        ),
        detail_strategy=DetailStrategy.LISTING_PAYLOAD,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(AMAZON_JOBS_CAREERS_URL,),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def fixture(name: str) -> HttpResponse:
    return HttpResponse("", "", 200, "application/json", 0, (FIXTURES / name).read_bytes())


def adapter_for(
    responses: list[HttpResponse], *, page_size: int = 1
) -> tuple[AmazonJobsAdapter, RouteTransport]:
    transport = RouteTransport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return AmazonJobsAdapter(client, page_size=page_size), transport


def test_count_checked_pagination_maps_full_descriptions_dates_and_aws_metadata() -> None:
    adapter, transport = adapter_for([fixture("page_1.json"), fixture("page_2.json")])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 2
    assert [job.external_job_id for job in result.jobs] == ["10561102", "SF260123206"]
    first = result.jobs[0]
    assert first.canonical_url == (
        "https://www.amazon.jobs/en/jobs/10561102/"
        "controls-technician-controls-deployment-service-india"
    )
    assert first.location_normalized == ("hyderabad", "telangana", "ind", "onsite")
    assert first.published_at == date(2026, 9, 28)
    assert first.date_basis is DateBasis.PUBLISHED
    assert first.description == (
        "Description\n\nOperate automation systems for AWS data centers.\n\n"
        "Partner with engineering teams.\n\nBasic qualifications\n\n"
        "2+ years of relevant work experience\n\nPreferred qualifications\n\n"
        "Experience in data center engineering"
    )
    assert first.description_hash is not None
    assert first.source_metadata["business_category"] == "aws"
    assert first.source_metadata["aws_owned"] is True
    assert result.jobs[1].source_metadata["aws_owned"] is False
    assert result.jobs[1].published_at == date(2026, 9, 9)
    assert result.jobs[1].published_at_raw == "September  9, 2026"
    assert transport.calls == [
        "https://www.amazon.jobs/en/search.json?base_query=&country=IND&offset=0&result_limit=1&sort=recent",
        "https://www.amazon.jobs/en/search.json?base_query=&country=IND&offset=1&result_limit=1&sort=recent",
    ]


def test_empty_malformed_duplicate_and_total_drift_fail_closed() -> None:
    empty, _ = adapter_for([fixture("empty.json")], page_size=100)
    empty_result = empty.list_jobs(source())
    assert empty_result.outcome is AdapterOutcome.EMPTY
    assert empty_result.complete is True

    page = json.loads((FIXTURES / "page_1.json").read_text(encoding="utf-8"))
    page["jobs"][0]["country_code"] = "USA"
    malformed, _ = adapter_for(
        [
            HttpResponse("", "", 200, "application/json", 0, json.dumps(page).encode()),
            fixture("page_2.json"),
        ]
    )
    malformed_result = malformed.list_jobs(source())
    assert malformed_result.outcome is AdapterOutcome.PARTIAL
    assert malformed_result.diagnostics[-1].category == "malformed_job"

    duplicate, _ = adapter_for([fixture("page_1.json"), fixture("page_1.json")])
    duplicate_result = duplicate.list_jobs(source())
    assert duplicate_result.outcome is AdapterOutcome.SUSPICIOUS
    assert duplicate_result.diagnostics[-1].category == "duplicate_job_id"

    changed = json.loads((FIXTURES / "page_2.json").read_text(encoding="utf-8"))
    changed["hits"] = 3
    drift, _ = adapter_for(
        [
            fixture("page_1.json"),
            HttpResponse("", "", 200, "application/json", 0, json.dumps(changed).encode()),
        ]
    )
    drift_result = drift.list_jobs(source())
    assert drift_result.outcome is AdapterOutcome.SUSPICIOUS
    assert drift_result.diagnostics[-1].category == "changing_total"


def test_invalid_source_configuration_is_rejected_before_network() -> None:
    adapter, transport = adapter_for([fixture("empty.json")])
    with pytest.raises(AdapterConfigurationError, match="adapter_key=amazon_jobs_india"):
        adapter.list_jobs(replace(source(), adapter_parameters={"adapter_key": "other"}))
    with pytest.raises(AdapterConfigurationError, match="requires careers_url"):
        adapter.list_jobs(replace(source(), careers_url="https://www.amazon.jobs/en/search"))
    assert transport.calls == []
