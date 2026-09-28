"""Fixture-backed tests for Gnani.ai's public careers API."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError
from job_finder.adapters.gnani_careers import (
    GNANI_ADAPTER_KEY,
    GNANI_CAREERS_URL,
    GNANI_JOBS_API,
    GnaniCareersAdapter,
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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "gnani_careers"


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
        company_id="gnani-ai",
        company_name="Gnani.ai",
        status=SourceStatus.REVIEWED,
        careers_url=GNANI_CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": GNANI_ADAPTER_KEY},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "positionPublishDate",
            DateBasis.PUBLISHED,
            True,
            "Public jobs API publication date.",
        ),
        detail_strategy=DetailStrategy.DETAIL_PAGE,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(GNANI_CAREERS_URL, GNANI_JOBS_API),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def response(
    body: bytes,
    *,
    content_type: str,
    final_url: str = "",
) -> HttpResponse:
    return HttpResponse("", final_url, 200, content_type, 0, body)


def adapter_for(responses: list[HttpResponse]) -> tuple[GnaniCareersAdapter, RouteTransport]:
    transport = RouteTransport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return GnaniCareersAdapter(client), transport


def listing_response(payload: dict[str, object] | None = None) -> HttpResponse:
    body = (
        json.dumps(payload).encode()
        if payload is not None
        else (FIXTURES / "jobs.json").read_bytes()
    )
    return response(body, content_type="application/json")


def detail_response(*, final_url: str = "") -> HttpResponse:
    return response(
        (FIXTURES / "detail.html").read_bytes(),
        content_type="text/html",
        final_url=final_url,
    )


def test_complete_api_maps_identity_dates_locations_and_deferred_detail() -> None:
    adapter, transport = adapter_for([listing_response(), detail_response()])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 1
    assert [job.external_job_id for job in result.jobs] == [
        "AI-Ben-2026-09-28-142",
        "Dev--2026-05-07-80",
    ]
    first, second = result.jobs
    assert first.title_original == "AI Engineer"
    assert first.location_original == "Bengaluru"
    assert first.published_at is not None
    assert first.published_at.isoformat() == "2026-09-28"
    assert first.date_basis is DateBasis.PUBLISHED
    assert first.description is None
    assert first.source_metadata["minimum_experience_years"] == 2
    assert second.location_original == "Remote"
    assert second.source_metadata["location_defaulted_from_null"] is True
    assert result.diagnostics[-1].category == "null_location_is_remote"

    detailed = adapter.get_job_detail(source(), first)
    assert detailed.description is not None
    assert "production machine-learning systems" in detailed.description
    assert "Skills Required" in detailed.description
    assert detailed.description_hash is not None
    assert transport.calls == [GNANI_JOBS_API, first.canonical_url]


def test_total_mismatch_malformed_date_duplicate_and_redirect_fail_closed() -> None:
    payload = json.loads((FIXTURES / "jobs.json").read_text(encoding="utf-8"))
    payload["data"]["total"] = 3
    mismatch, _ = adapter_for([listing_response(payload)])
    assert mismatch.list_jobs(source()).outcome is AdapterOutcome.FAILED

    payload = json.loads((FIXTURES / "jobs.json").read_text(encoding="utf-8"))
    payload["data"]["jobs"][0]["positionPublishDate"] = "today"
    malformed, _ = adapter_for([listing_response(payload)])
    malformed_result = malformed.list_jobs(source())
    assert malformed_result.outcome is AdapterOutcome.FAILED
    assert malformed_result.diagnostics[-1].category == "malformed_job"

    payload = json.loads((FIXTURES / "jobs.json").read_text(encoding="utf-8"))
    payload["data"]["jobs"][1]["code"] = payload["data"]["jobs"][0]["code"]
    duplicate, _ = adapter_for([listing_response(payload)])
    assert duplicate.list_jobs(source()).outcome is AdapterOutcome.SUSPICIOUS

    redirected, _ = adapter_for(
        [
            response(
                (FIXTURES / "jobs.json").read_bytes(),
                content_type="application/json",
                final_url="https://example.com/api/jobs",
            )
        ]
    )
    assert redirected.list_jobs(source()).outcome is AdapterOutcome.FAILED


def test_detail_schema_and_source_configuration_are_strict() -> None:
    adapter, _ = adapter_for([listing_response(), detail_response()])
    job = adapter.list_jobs(source()).jobs[0]
    bad_detail = (
        (FIXTURES / "detail.html")
        .read_text(encoding="utf-8")
        .replace("Responsibilities", "Overview")
    )
    broken, _ = adapter_for([response(bad_detail.encode(), content_type="text/html")])
    with pytest.raises(ValueError, match="Responsibilities"):
        broken.get_job_detail(source(), job)

    configured, transport = adapter_for([])
    with pytest.raises(AdapterConfigurationError, match="adapter_key=gnani_careers_api"):
        configured.list_jobs(replace(source(), adapter_parameters={"adapter_key": "other"}))
    with pytest.raises(AdapterConfigurationError, match="requires careers_url"):
        configured.list_jobs(replace(source(), careers_url="https://gnani.ai/careers"))
    assert transport.calls == []
