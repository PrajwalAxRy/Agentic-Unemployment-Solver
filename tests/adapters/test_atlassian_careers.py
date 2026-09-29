"""Fixture-backed tests for Atlassian's public careers inventory."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.atlassian_careers import (
    ATLASSIAN_ADAPTER_KEY,
    ATLASSIAN_CAREERS_URL,
    ATLASSIAN_LISTINGS_URL,
    AtlassianCareersAdapter,
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

FIXTURE = Path(__file__).parents[1] / "fixtures" / "atlassian_careers" / "listings.json"


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
        company_id="atlassian",
        company_name="Atlassian",
        status=SourceStatus.REVIEWED,
        careers_url=ATLASSIAN_CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": ATLASSIAN_ADAPTER_KEY},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "portalJobPost.updatedDate",
            DateBasis.UNKNOWN,
            False,
            "iCIMS updated date is not verified as publication evidence.",
        ),
        detail_strategy=DetailStrategy.LISTING_PAYLOAD,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(ATLASSIAN_CAREERS_URL, ATLASSIAN_LISTINGS_URL),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def response(body: bytes, *, final_url: str = "") -> HttpResponse:
    return HttpResponse("", final_url, 200, "application/json", 0, body)


def adapter_for(responses: list[HttpResponse]) -> tuple[AtlassianCareersAdapter, Transport]:
    transport = Transport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return AtlassianCareersAdapter(client), transport


def test_inventory_collapses_consistent_variants_and_preserves_unknown_dates() -> None:
    adapter, transport = adapter_for([response(FIXTURE.read_bytes())])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 1
    assert [job.external_job_id for job in result.jobs] == ["1001", "1002"]
    first, second = result.jobs
    # Phase 1: the shared adapter-side normalizer splits on commas, so the postcode tail
    # becomes its own token. Verified not to change the filter verdict -- filter_location
    # returns pass/accepted_india_location either way, because _contains_phrase matches
    # "india" inside whichever token carries it (docs/rewrite/phase1_normalization_impact.md).
    assert first.location_normalized == (
        "bengaluru - india - bengaluru",
        "560071 india",
        "remote - india - remote",
    )
    assert first.date_basis is DateBasis.UNKNOWN
    assert first.published_at is not None
    assert first.description is not None
    assert "model-serving systems" in first.description
    assert first.source_metadata["portal_ids"] == (242,)
    assert second.location_original == "location unavailable"
    assert [item.category for item in result.diagnostics] == [
        "duplicate_portal_variants_collapsed",
        "missing_location",
        "unverified_updated_date",
    ]
    assert transport.calls == [ATLASSIAN_LISTINGS_URL]


def test_inconsistent_variant_malformed_date_empty_and_redirect_fail_closed() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload[1]["title"] = "Different Role"
    inconsistent, _ = adapter_for([response(json.dumps(payload).encode())])
    assert inconsistent.list_jobs(source()).outcome is AdapterOutcome.FAILED

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload[0]["portalJobPost"]["updatedDate"] = "today"
    payload[1]["portalJobPost"]["updatedDate"] = "today"
    malformed, _ = adapter_for([response(json.dumps(payload).encode())])
    assert malformed.list_jobs(source()).outcome is AdapterOutcome.FAILED

    empty, _ = adapter_for([response(b"[]")])
    assert empty.list_jobs(source()).outcome is AdapterOutcome.FAILED

    redirected, _ = adapter_for(
        [response(FIXTURE.read_bytes(), final_url="https://example.com/jobs")]
    )
    assert redirected.list_jobs(source()).outcome is AdapterOutcome.FAILED


def test_source_configuration_is_strict() -> None:
    adapter, transport = adapter_for([])
    with pytest.raises(AdapterConfigurationError, match="adapter_key=atlassian_careers_inventory"):
        adapter.list_jobs(replace(source(), adapter_parameters={"adapter_key": "other"}))
    with pytest.raises(AdapterConfigurationError, match="requires careers_url"):
        adapter.list_jobs(
            replace(source(), careers_url="https://www.atlassian.com/company/careers")
        )
    assert transport.calls == []
