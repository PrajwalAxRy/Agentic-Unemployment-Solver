"""Fixture-backed tests for Navi's public careers API."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError
from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy, HttpResponse
from job_finder.adapters.navi_careers import (
    NAVI_ADAPTER_KEY,
    NAVI_CAREERS_URL,
    NAVI_JOBS_API,
    NaviCareersAdapter,
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

FIXTURE = Path(__file__).parents[1] / "fixtures" / "navi_careers" / "jobs.json"


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
        company_id="navi",
        company_name="Navi",
        status=SourceStatus.REVIEWED,
        careers_url=NAVI_CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": NAVI_ADAPTER_KEY},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "PublishedDate", DateBasis.PUBLISHED, True, "Public API publication timestamp."
        ),
        detail_strategy=DetailStrategy.LISTING_PAYLOAD,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(NAVI_CAREERS_URL, NAVI_JOBS_API),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def payload() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def response(value: dict[str, object], *, final_url: str = "") -> HttpResponse:
    return HttpResponse("", final_url, 200, "application/json", 0, json.dumps(value).encode())


def adapter_for(responses: list[HttpResponse]) -> tuple[NaviCareersAdapter, RouteTransport]:
    transport = RouteTransport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return NaviCareersAdapter(client), transport


def test_complete_collection_maps_identity_location_date_and_description() -> None:
    adapter, transport = adapter_for([response(payload())])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 1
    assert len(result.jobs) == 2
    first, second = result.jobs
    assert first.external_job_id == "2f237a6a-b440-47ef-9a78-c340d8ee3415"
    assert first.title_normalized == "machine learning engineer"
    assert first.location_normalized == ("bengaluru", "karnataka", "india")
    assert first.date_basis is DateBasis.PUBLISHED
    assert first.published_at is not None
    assert first.published_at.isoformat() == "2026-09-28T06:38:13.657165+00:00"
    assert (
        first.description
        == "Build production ML systems.\n\nTrain models.\n\nEvaluate reliability."
    )
    assert first.description_hash is not None
    assert second.location_original == "Bangalore, Karnataka, India | Delhi, India"
    assert first.source_metadata["company_name"] == "Navi Limited"
    assert transport.calls == [NAVI_JOBS_API]


def test_total_mismatch_duplicate_and_redirect_fail_closed() -> None:
    mismatched = payload()
    mismatched["Total"] = 3
    adapter, _ = adapter_for([response(mismatched)])
    assert adapter.list_jobs(source()).outcome is AdapterOutcome.FAILED

    duplicate = payload()
    duplicate["Jobs"][1]["JobId"] = duplicate["Jobs"][0]["JobId"]  # type: ignore[index]
    duplicate["Jobs"][1]["ApplyUrl"] = duplicate["Jobs"][0]["ApplyUrl"]  # type: ignore[index]
    adapter, _ = adapter_for([response(duplicate)])
    assert adapter.list_jobs(source()).outcome is AdapterOutcome.SUSPICIOUS

    adapter, _ = adapter_for([response(payload(), final_url="https://example.com/jobs")])
    assert adapter.list_jobs(source()).outcome is AdapterOutcome.FAILED


def test_malformed_row_is_skipped_without_discarding_the_rest() -> None:
    """One unparseable row must not discard the rows after it.

    The 2026-10-01 run returned early on the first malformed row and kept 4 of Navi's 36
    jobs. Greenhouse and Ashby skip and continue; Navi now does too, while still reporting
    the source as incomplete.
    """
    malformed = payload()
    malformed["Jobs"][0]["Location"] = "not-json"  # type: ignore[index]

    result = adapter_for([response(malformed)])[0].list_jobs(source())

    assert result.outcome is AdapterOutcome.PARTIAL
    assert result.complete is False
    assert [job.external_job_id for job in result.jobs] == [
        malformed["Jobs"][1]["JobId"].casefold()  # type: ignore[index]
    ]
    assert [item.category for item in result.diagnostics] == ["malformed_job"]


@pytest.mark.parametrize(
    "company_name",
    ["Navi", "Navi Limited", "NAVI TECHNOLOGIES LIMITED", "navi technologies limited"],
)
def test_navi_group_legal_entities_are_accepted(company_name: str) -> None:
    """Requisitions are owned by several Navi legal entities, all of them legitimate."""
    value = payload()
    value["Jobs"][0]["CompanyName"] = company_name  # type: ignore[index]

    result = adapter_for([response(value)])[0].list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert len(result.jobs) == 2
    assert result.jobs[0].source_metadata["company_name"] == company_name


@pytest.mark.parametrize("company_name", ["Navigator Systems", "Acme Corp", "Not Navi Ltd"])
def test_unrelated_company_names_are_still_rejected(company_name: str) -> None:
    """Widening the entity check must not accept a substring match from another company."""
    value = payload()
    value["Jobs"][0]["CompanyName"] = company_name  # type: ignore[index]

    result = adapter_for([response(value)])[0].list_jobs(source())

    assert result.outcome is AdapterOutcome.PARTIAL
    assert [item.category for item in result.diagnostics] == ["malformed_job"]
    assert len(result.jobs) == 1


def test_every_row_failing_is_reported_as_failed_not_partial() -> None:
    """Total loss must not be reported as a partial read.

    A schema change or a renamed legal entity fails every row at once. PARTIAL with zero
    jobs would present that as "we got some of the source".
    """
    value = payload()
    for raw_job in value["Jobs"]:  # type: ignore[attr-defined]
        raw_job["CompanyName"] = "Unrelated Corp"

    result = adapter_for([response(value)])[0].list_jobs(source())

    assert result.outcome is AdapterOutcome.FAILED
    assert result.complete is False
    assert result.jobs == ()
    assert [item.category for item in result.diagnostics] == ["malformed_job"] * 2


def test_source_configuration_is_strict() -> None:
    adapter, transport = adapter_for([])
    with pytest.raises(AdapterConfigurationError, match="adapter_key=navi_public_careers_api"):
        adapter.list_jobs(replace(source(), adapter_parameters={"adapter_key": "other"}))
    with pytest.raises(AdapterConfigurationError, match="requires careers_url"):
        adapter.list_jobs(replace(source(), careers_url="https://navi.com/careers"))
    assert transport.calls == []
