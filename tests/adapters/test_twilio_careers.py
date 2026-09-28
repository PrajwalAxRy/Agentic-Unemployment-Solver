"""Fixture-backed tests for Twilio's branded public careers APIs."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError, JobDetailAdapter
from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy, HttpResponse
from job_finder.adapters.twilio_careers import (
    TWILIO_ADAPTER_KEY,
    TWILIO_CAREERS_URL,
    TwilioCareersAdapter,
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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "twilio_careers"


class Transport:
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
        company_id="twilio",
        company_name="Twilio",
        status=SourceStatus.REVIEWED,
        careers_url=TWILIO_CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": TWILIO_ADAPTER_KEY},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "efcustomTextPostDate",
            DateBasis.PUBLISHED,
            True,
            "The detail UI labels this value Date posted.",
        ),
        detail_strategy=DetailStrategy.DETAIL_ENDPOINT,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(TWILIO_CAREERS_URL,),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def response(name: str, *, final_url: str = "") -> HttpResponse:
    return HttpResponse("", final_url, 200, "application/json", 0, (FIXTURES / name).read_bytes())


def raw_response(payload: object) -> HttpResponse:
    return HttpResponse("", "", 200, "application/json", 0, json.dumps(payload).encode())


def adapter_for(
    responses: list[HttpResponse],
) -> tuple[TwilioCareersAdapter, Transport]:
    transport = Transport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return TwilioCareersAdapter(client), transport


def test_pagination_and_detail_preserve_identity_and_verify_visible_date() -> None:
    adapter, transport = adapter_for(
        [response("page1.json"), response("page2.json"), response("detail.json")]
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 2
    assert len(result.jobs) == 3
    first = result.jobs[0]
    assert first.external_job_id == "1099556260796"
    assert first.location_normalized == ("remote - us",)
    assert first.date_basis is DateBasis.UNKNOWN
    assert first.description is None
    assert result.diagnostics[0].category == "unverified_creation_timestamp"
    assert isinstance(adapter, JobDetailAdapter)

    detailed = adapter.get_job_detail(source(), first)

    assert detailed.external_job_id == first.external_job_id
    assert detailed.date_basis is DateBasis.PUBLISHED
    assert detailed.published_at is not None
    assert detailed.published_at.isoformat() == "2026-09-23"
    assert detailed.description is not None
    assert "developer evangelism strategy" in detailed.description
    assert detailed.source_metadata["visible_date_posted_verified"] is True
    assert "start=0" in transport.calls[0]
    assert "start=10" in transport.calls[1]
    assert "position_details?position_id=1099556260796" in transport.calls[2]


def test_changed_total_duplicate_and_redirect_fail_closed() -> None:
    page2 = json.loads((FIXTURES / "page2.json").read_text(encoding="utf-8"))
    page2["data"]["count"] = 4
    changed, _ = adapter_for([response("page1.json"), raw_response(page2)])
    assert changed.list_jobs(source()).outcome is AdapterOutcome.SUSPICIOUS

    page2 = json.loads((FIXTURES / "page2.json").read_text(encoding="utf-8"))
    page2["data"]["positions"][0]["id"] = 1099556260796
    page2["data"]["positions"][0]["positionUrl"] = "/careers/job/1099556260796"
    duplicate, _ = adapter_for([response("page1.json"), raw_response(page2)])
    assert duplicate.list_jobs(source()).outcome is AdapterOutcome.SUSPICIOUS

    redirected, _ = adapter_for([response("page1.json", final_url="https://example.com/api/jobs")])
    assert redirected.list_jobs(source()).outcome is AdapterOutcome.FAILED


def test_detail_and_source_configuration_are_strict() -> None:
    adapter, _ = adapter_for([response("page1.json"), response("page2.json")])
    job = adapter.list_jobs(source()).jobs[0]
    detail = json.loads((FIXTURES / "detail.json").read_text(encoding="utf-8"))
    detail["data"]["efcustomTextPostDate"] = ["today"]
    broken, _ = adapter_for([raw_response(detail)])
    with pytest.raises(ValueError, match="publication date was invalid"):
        broken.get_job_detail(source(), job)

    strict, transport = adapter_for([])
    with pytest.raises(AdapterConfigurationError, match="adapter_key=twilio_public"):
        strict.list_jobs(replace(source(), adapter_parameters={"adapter_key": "other"}))
    with pytest.raises(AdapterConfigurationError, match="requires careers_url"):
        strict.list_jobs(replace(source(), careers_url="https://jobs.twilio.com/careers"))
    assert transport.calls == []
