"""Fixture-backed tests for Apple's public India jobs hydration payloads."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from job_finder.adapters.apple_jobs import (
    APPLE_JOBS_ADAPTER_KEY,
    APPLE_JOBS_CAREERS_URL,
    AppleJobsAdapter,
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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "apple_jobs"


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
        company_id="apple",
        company_name="Apple",
        status=SourceStatus.REVIEWED,
        careers_url=APPLE_JOBS_CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": APPLE_JOBS_ADAPTER_KEY},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "postDateInGMT", DateBasis.PUBLISHED, True, "Apple publication timestamp."
        ),
        detail_strategy=DetailStrategy.DETAIL_PAGE,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(APPLE_JOBS_CAREERS_URL,),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def fixture(name: str) -> HttpResponse:
    return HttpResponse("", "", 200, "text/html", 0, (FIXTURES / name).read_bytes())


def adapter_for(
    responses: list[HttpResponse], *, page_size: int = 1
) -> tuple[AppleJobsAdapter, RouteTransport]:
    transport = RouteTransport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return AppleJobsAdapter(client, page_size=page_size), transport


def test_count_checked_hydration_pagination_maps_pipeline_and_requisition_jobs() -> None:
    adapter, transport = adapter_for([fixture("page_1.html"), fixture("page_2.html")])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 2
    assert [job.external_job_id for job in result.jobs] == [
        "PIPE-200313970",
        "200683493-0321",
    ]
    pipeline, requisition = result.jobs
    assert pipeline.canonical_url == (
        "https://jobs.apple.com/en-us/details/200313970/in-business-expert"
    )
    assert pipeline.location_normalized == ("india",)
    assert pipeline.published_at is None
    assert pipeline.published_at_raw == "2026-09-28T10:48:48.066345893Z"
    assert pipeline.date_basis is DateBasis.UNKNOWN
    assert pipeline.description is None
    assert pipeline.source_metadata["managed_pipeline_role"] is True
    assert pipeline.source_metadata["team_name"] == "Apple Retail"
    assert requisition.canonical_url == (
        "https://jobs.apple.com/en-us/details/200683493-0321/application-reliability-engineer"
    )
    assert requisition.location_original == "Bengaluru, Karnataka, India"
    assert requisition.published_at == datetime(
        2026, 9, 19, 1, 40, 29, 163000, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )
    assert transport.calls == [APPLE_JOBS_CAREERS_URL, f"{APPLE_JOBS_CAREERS_URL}&page=2"]


def test_detail_hydration_maps_all_substantive_sections_and_preserves_identity() -> None:
    listing_adapter, _ = adapter_for([fixture("page_1.html"), fixture("page_2.html")])
    listed = listing_adapter.list_jobs(source()).jobs[1]
    detail_adapter, transport = adapter_for([fixture("detail.html")])

    detailed = detail_adapter.get_job_detail(source(), listed)

    assert detailed.external_job_id == listed.external_job_id
    assert detailed.canonical_url == listed.canonical_url
    assert detailed.description == (
        "Summary\n\nBuild reliable payments systems.\n\n"
        "Description\n\nOwn the operational health of a distributed platform.\n\n"
        "Responsibilities\n\nDiagnose failures.\nAutomate permanent fixes.\n\n"
        "Minimum qualifications\n\n3+ years of software engineering experience.\n\n"
        "Preferred qualifications\n\nExperience with Kubernetes."
    )
    assert "INTERNAL_STATE" not in detailed.description
    assert detailed.description_hash is not None
    assert detailed.source_metadata["employment_type"] == "Standard"
    assert detailed.source_metadata["job_type"] == "CORPORATE"
    assert transport.calls == [listed.canonical_url]


def test_malformed_duplicate_and_count_drift_fail_closed() -> None:
    malformed = (
        (FIXTURES / "page_1.html")
        .read_text(encoding="utf-8")
        .replace('\\"reqId\\":\\"PIPE-200313970\\"', '\\"reqId\\":\\"PIPE-999\\"')
    )
    malformed_adapter, _ = adapter_for(
        [HttpResponse("", "", 200, "text/html", 0, malformed.encode())]
    )
    malformed_result = malformed_adapter.list_jobs(source())
    assert malformed_result.outcome is AdapterOutcome.FAILED
    assert malformed_result.diagnostics[-1].category == "malformed_job"

    duplicate_page = (
        (FIXTURES / "page_2.html")
        .read_text(encoding="utf-8")
        .replace("200683493-0321", "PIPE-200313970")
        .replace("REQ-200683493", "PIPE-200313970")
        .replace("200683493", "200313970")
        .replace('\\"managedPipelineRole\\":false', '\\"managedPipelineRole\\":true')
        .replace('\\"type\\":\\"REQ\\"', '\\"type\\":\\"PIPE\\"')
    )
    duplicate, _ = adapter_for(
        [
            fixture("page_1.html"),
            HttpResponse("", "", 200, "text/html", 0, duplicate_page.encode()),
        ]
    )
    duplicate_result = duplicate.list_jobs(source())
    assert duplicate_result.outcome is AdapterOutcome.SUSPICIOUS
    assert duplicate_result.diagnostics[-1].category == "duplicate_job_id"

    drift_page = (
        (FIXTURES / "page_2.html")
        .read_text(encoding="utf-8")
        .replace('\\"totalRecords\\":2', '\\"totalRecords\\":3')
    )
    drift, _ = adapter_for(
        [
            fixture("page_1.html"),
            HttpResponse("", "", 200, "text/html", 0, drift_page.encode()),
        ]
    )
    drift_result = drift.list_jobs(source())
    assert drift_result.outcome is AdapterOutcome.SUSPICIOUS
    assert drift_result.diagnostics[-1].category == "changing_total"


def test_invalid_source_configuration_is_rejected_before_network() -> None:
    adapter, transport = adapter_for([fixture("page_1.html")])
    with pytest.raises(AdapterConfigurationError, match="adapter_key=apple_jobs_india"):
        adapter.list_jobs(replace(source(), adapter_parameters={"adapter_key": "other"}))
    with pytest.raises(AdapterConfigurationError, match="requires careers_url"):
        adapter.list_jobs(replace(source(), careers_url="https://jobs.apple.com/en-us/search"))
    assert transport.calls == []
