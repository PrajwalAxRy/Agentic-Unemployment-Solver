"""Fixture-style tests for SmartRecruiters public postings."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from job_finder.adapters.base import AdapterConfigurationError, JobDetailAdapter
from job_finder.adapters.http_client import (
    BoundedHttpClient,
    HttpFailureCategory,
    HttpPolicy,
    HttpRequestError,
    HttpResponse,
)
from job_finder.adapters.smartrecruiters import SmartRecruitersAdapter
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


class RouteTransport:
    def __init__(self, outcomes: list[HttpResponse | HttpRequestError]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    def get(self, url: str, **_: object) -> HttpResponse:
        self.calls.append(url)
        result = self.outcomes.pop(0)
        if isinstance(result, HttpRequestError):
            raise result
        return replace(result, requested_url=url, final_url=url)


def source() -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id="example",
        company_name="Example",
        status=SourceStatus.REVIEWED,
        careers_url="https://careers.smartrecruiters.com/Example",
        adapter_type=AdapterType.SMARTRECRUITERS,
        adapter_parameters={"company_identifier": "Example"},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "releasedDate", DateBasis.PUBLISHED, True, "Public release timestamp."
        ),
        detail_strategy=DetailStrategy.DETAIL_ENDPOINT,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=("https://careers.smartrecruiters.com/Example",),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def response(payload: object, content_type: str = "application/json") -> HttpResponse:
    return HttpResponse("", "", 200, content_type, 0, json.dumps(payload).encode())


def job(identifier: str) -> dict[str, object]:
    return {
        "id": identifier,
        "name": f"ML Engineer {identifier}",
        "releasedDate": "2026-09-20T07:40:46.000Z",
        "location": {"fullLocation": "Bengaluru, KA, India", "remote": False, "hybrid": True},
        "ref": f"https://api.smartrecruiters.com/v1/companies/Example/postings/{identifier}",
        "uuid": identifier,
    }


def adapter_for(
    outcomes: list[HttpResponse | HttpRequestError],
) -> tuple[SmartRecruitersAdapter, RouteTransport]:
    transport = RouteTransport(outcomes)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return SmartRecruitersAdapter(client, page_size=2), transport


def test_count_checked_pagination_maps_identity_location_url_and_date() -> None:
    adapter, transport = adapter_for(
        [
            response({"content": [job("one"), job("two")], "totalFound": 3}),
            response({"content": [job("three")], "totalFound": 3}),
        ]
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 2
    assert [item.external_job_id for item in result.jobs] == ["one", "two", "three"]
    assert result.jobs[0].location_normalized == ("bengaluru", "ka", "india")
    assert result.jobs[0].canonical_url == "https://jobs.smartrecruiters.com/Example/one"
    assert result.jobs[0].date_basis is DateBasis.PUBLISHED
    assert transport.calls[1].endswith("limit=2&offset=2")


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
    second_page = [job("three"), job("four")] if totals[1] == 4 else [job("three")]
    adapter, _ = adapter_for(
        [
            response({"content": [job("one"), job("two")], "totalFound": totals[0]}),
            response({"content": second_page, "totalFound": totals[1]}),
        ]
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert len(result.jobs) == totals[1]
    assert result.diagnostics[-1].category == "inventory_total_changed"


def test_empty_malformed_access_and_partial_responses_are_visible() -> None:
    empty, _ = adapter_for([response({"content": [], "totalFound": 0})])
    assert empty.list_jobs(source()).outcome is AdapterOutcome.EMPTY

    malformed, _ = adapter_for([response({"content": "wrong", "totalFound": 1})])
    assert malformed.list_jobs(source()).outcome is AdapterOutcome.FAILED

    blocked, _ = adapter_for([HttpRequestError(HttpFailureCategory.ACCESS_BLOCK, "access blocked")])
    assert blocked.list_jobs(source()).outcome is AdapterOutcome.BLOCKED

    partial, _ = adapter_for(
        [
            response({"content": [job("one"), job("two")], "totalFound": 3}),
            HttpRequestError(HttpFailureCategory.TIMEOUT, "request timed out", retryable=True),
        ]
    )
    assert partial.list_jobs(source()).outcome is AdapterOutcome.PARTIAL


def test_detail_description_preserves_listing_identity() -> None:
    adapter, _ = adapter_for(
        [
            response({"content": [job("one")], "totalFound": 1}),
            response(
                {
                    "id": "one",
                    "jobAd": {"sections": {"jobDescription": "Build reliable ML systems."}},
                }
            ),
        ]
    )
    listing = adapter.list_jobs(source()).jobs[0]

    assert isinstance(adapter, JobDetailAdapter)
    detailed = adapter.get_job_detail(source(), listing)
    assert detailed.external_job_id == listing.external_job_id
    assert detailed.canonical_url == listing.canonical_url
    assert detailed.description == "Build reliable ML systems."
    assert detailed.description_hash is not None


def test_invalid_source_and_duplicate_ids_are_rejected() -> None:
    adapter, _ = adapter_for([response({"content": [], "totalFound": 0})])
    with pytest.raises(AdapterConfigurationError):
        adapter.list_jobs(replace(source(), adapter_type=AdapterType.ASHBY))

    duplicate, _ = adapter_for([response({"content": [job("one"), job("one")], "totalFound": 2})])
    assert duplicate.list_jobs(source()).outcome is AdapterOutcome.SUSPICIOUS
