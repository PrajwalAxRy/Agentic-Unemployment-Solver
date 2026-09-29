"""Fixture-backed tests for the D. E. Shaw India public careers index."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError
from job_finder.adapters.deshaw_india import (
    DESHAW_INDIA_ADAPTER_KEY,
    DESHAW_INDIA_CAREERS_URL,
    DeshawIndiaAdapter,
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

FIXTURE = Path(__file__).parents[1] / "fixtures" / "deshaw_india" / "careers.html"


class RouteTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **_: object) -> HttpResponse:
        self.calls.append(url)
        response = self.responses.pop(0)
        return replace(
            response,
            requested_url=url,
            final_url=response.final_url or url,
        )


def source() -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id="d-e-shaw-india",
        company_name="D. E. Shaw India",
        status=SourceStatus.REVIEWED,
        careers_url=DESHAW_INDIA_CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": DESHAW_INDIA_ADAPTER_KEY},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            None,
            DateBasis.UNKNOWN,
            False,
            "The official public job contract exposes no publication timestamp.",
        ),
        detail_strategy=DetailStrategy.LISTING_PAYLOAD,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(DESHAW_INDIA_CAREERS_URL,),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def response(body: bytes | None = None, *, final_url: str = "") -> HttpResponse:
    return HttpResponse(
        "",
        final_url,
        200,
        "text/html",
        0,
        body if body is not None else FIXTURE.read_bytes(),
    )


def adapter_for(responses: list[HttpResponse]) -> tuple[DeshawIndiaAdapter, RouteTransport]:
    transport = RouteTransport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return DeshawIndiaAdapter(client), transport


def test_public_regular_jobs_map_identity_locations_and_complete_descriptions() -> None:
    adapter, transport = adapter_for([response()])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 1
    assert [job.external_job_id for job in result.jobs] == ["7337", "2781"]
    first = result.jobs[0]
    # Phase 1: shared normalize_title strips punctuation (to_change.md 1.2).
    assert first.title_normalized == "lead tech python infra"
    assert first.location_original == "Hyderabad, Bengaluru"
    assert first.location_normalized == ("hyderabad", "bengaluru")
    assert first.canonical_url == (
        "https://www.deshawindia.com/careers/lead-tech-python-infra-7337"
    )
    assert first.date_basis is DateBasis.UNKNOWN
    assert first.published_at is None
    assert first.description == (
        "Build and maintain Python infrastructure.\n\n"
        "Design reliable developer platforms.\n\n"
        "Partner with engineering teams.\n\n"
        "Three years of Python experience."
    )
    assert first.description_hash is not None
    assert first.source_metadata["department"] == "Core Tech"
    assert first.source_metadata["location_abbreviations"] == ("HYD", "BLR")
    assert result.jobs[1].source_metadata["is_exploratory"] is True
    assert result.diagnostics[-1].category == "missing_publication_date"
    assert transport.calls == [DESHAW_INDIA_CAREERS_URL]


def test_internal_jobs_are_not_emitted_and_empty_public_array_is_valid() -> None:
    page = FIXTURE.read_text(encoding="utf-8")
    start = page.index('            "regularJobs": [')
    end = page.index('            "internalJobs": [')
    empty_page = page[:start] + '            "regularJobs": [],\n' + page[end:]
    adapter, _ = adapter_for([response(empty_page.encode())])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.EMPTY
    assert result.complete is True
    assert result.jobs == ()


def test_fetch_error_malformed_job_duplicate_and_redirect_fail_closed() -> None:
    page = FIXTURE.read_text(encoding="utf-8")

    fetch_error, _ = adapter_for(
        [response(page.replace('"jobsFetchingError": false', '"jobsFetchingError": true').encode())]
    )
    assert fetch_error.list_jobs(source()).outcome is AdapterOutcome.FAILED

    malformed, _ = adapter_for(
        [
            response(
                page.replace(
                    '"jobUrl": "Lead-Tech-Python-Infra-7337"', '"jobUrl": "wrong-7338"'
                ).encode()
            )
        ]
    )
    malformed_result = malformed.list_jobs(source())
    assert malformed_result.outcome is AdapterOutcome.FAILED
    assert malformed_result.diagnostics[-1].category == "malformed_job"

    duplicate, _ = adapter_for(
        [response(page.replace('"id": 2781', '"id": 7337').replace('-2781"', '-7337"').encode())]
    )
    duplicate_result = duplicate.list_jobs(source())
    assert duplicate_result.outcome is AdapterOutcome.SUSPICIOUS
    assert duplicate_result.diagnostics[-1].category == "duplicate_job_id"

    redirect, _ = adapter_for([response(final_url="https://example.com/careers")])
    redirect_result = redirect.list_jobs(source())
    assert redirect_result.outcome is AdapterOutcome.FAILED
    assert redirect_result.diagnostics[-1].category == "unexpected_redirect"


def test_invalid_source_configuration_is_rejected_before_network() -> None:
    adapter, transport = adapter_for([response()])
    with pytest.raises(AdapterConfigurationError, match="adapter_key=deshaw_india_index"):
        adapter.list_jobs(replace(source(), adapter_parameters={"adapter_key": "other"}))
    with pytest.raises(AdapterConfigurationError, match="requires careers_url"):
        adapter.list_jobs(replace(source(), careers_url="https://www.deshawindia.com/jobs"))
    assert transport.calls == []
