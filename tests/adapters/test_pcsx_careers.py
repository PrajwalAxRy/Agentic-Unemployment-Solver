"""Fixture-backed tests for reusable public PCSx careers surfaces."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError
from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy, HttpResponse
from job_finder.adapters.pcsx_careers import PCSX_ADAPTER_KEY, PcsxCareersAdapter
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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "pcsx_careers"
CAREERS_URL = "https://app.eightfold.ai/careers?domain=volkscience.com&hl=en"


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
        company_id="eightfold-ai",
        company_name="Eightfold AI",
        status=SourceStatus.REVIEWED,
        careers_url=CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={
            "adapter_key": PCSX_ADAPTER_KEY,
            "host": "app.eightfold.ai",
            "domain": "volkscience.com",
        },
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "postedTs", DateBasis.UNKNOWN, False, "PCSx timestamp basis is unverified."
        ),
        detail_strategy=DetailStrategy.DETAIL_ENDPOINT,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(CAREERS_URL,),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def response(value: dict[str, object], *, final_url: str = "") -> HttpResponse:
    return HttpResponse("", final_url, 200, "application/json", 0, json.dumps(value).encode())


def adapter_for(responses: list[HttpResponse]) -> tuple[PcsxCareersAdapter, RouteTransport]:
    transport = RouteTransport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return PcsxCareersAdapter(client), transport


def test_complete_collection_and_detail_map_identity_location_and_dates() -> None:
    adapter, transport = adapter_for(
        [response(fixture("page1.json")), response(fixture("detail.json"))]
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 1
    assert len(result.jobs) == 2
    first, second = result.jobs
    assert first.external_job_id == "68763995769"
    assert first.title_normalized == "test architect"
    assert first.location_original == "Bangalore"
    assert first.location_normalized == ("bangalore",)
    assert first.date_basis is DateBasis.UNKNOWN
    assert first.canonical_url == "https://app.eightfold.ai/careers/job/68763995769"
    assert second.location_original == "Location unavailable"
    assert second.source_metadata["listing_location_missing"] is True
    assert result.diagnostics[-1].category == "missing_location"

    detail = adapter.get_job_detail(source(), first)
    assert detail.description is not None
    assert "distributed AI platforms" in detail.description
    assert detail.description_hash is not None
    assert detail.published_at is not None
    assert detail.published_at_raw == "1789622583"
    assert detail.date_basis is DateBasis.UNKNOWN
    assert transport.calls == [
        "https://app.eightfold.ai/api/pcsx/search?domain=volkscience.com&query=&location=&start=0&&hl=en",
        "https://app.eightfold.ai/api/pcsx/position_details?position_id=68763995769&domain=volkscience.com&hl=en",
    ]


def test_total_drift_duplicate_schema_and_redirect_fail_closed() -> None:
    payload = fixture("page1.json")
    payload["data"]["positions"][1]["id"] = 68763995769  # type: ignore[index]
    payload["data"]["positions"][1]["positionUrl"] = "/careers/job/68763995769"  # type: ignore[index]
    duplicate, _ = adapter_for([response(payload)])
    assert duplicate.list_jobs(source()).outcome is AdapterOutcome.SUSPICIOUS

    malformed = fixture("page1.json")
    malformed["data"]["positions"][0]["locations"] = [123]  # type: ignore[index]
    adapter, _ = adapter_for([response(malformed)])
    assert adapter.list_jobs(source()).outcome is AdapterOutcome.FAILED

    redirected, _ = adapter_for(
        [response(fixture("page1.json"), final_url="https://example.com/api/pcsx/search")]
    )
    assert redirected.list_jobs(source()).outcome is AdapterOutcome.FAILED


def test_detail_timestamp_and_source_configuration_are_strict() -> None:
    listing_adapter, _ = adapter_for([response(fixture("page1.json"))])
    job = listing_adapter.list_jobs(source()).jobs[0]
    detail_payload = fixture("detail.json")
    detail_payload["data"]["externallyPostedTs"] = 1789622584  # type: ignore[index]
    broken, _ = adapter_for([response(detail_payload)])
    with pytest.raises(ValueError, match="did not agree"):
        broken.get_job_detail(source(), job)

    configured, transport = adapter_for([])
    with pytest.raises(AdapterConfigurationError, match="adapter_key=pcsx_public_careers"):
        configured.list_jobs(
            replace(
                source(),
                adapter_parameters={
                    "adapter_key": "other",
                    "host": "app.eightfold.ai",
                    "domain": "volkscience.com",
                },
            )
        )
    with pytest.raises(AdapterConfigurationError, match="careers_url"):
        configured.list_jobs(replace(source(), careers_url="https://app.eightfold.ai/careers"))
    assert transport.calls == []
