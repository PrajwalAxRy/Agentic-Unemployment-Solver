"""Fixture-backed tests for Qure.ai's embedded Zoho careers collection."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError
from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy, HttpResponse
from job_finder.adapters.qure_careers import (
    QURE_ADAPTER_KEY,
    QURE_CAREERS_URL,
    QureCareersAdapter,
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

FIXTURE = Path(__file__).parents[1] / "fixtures" / "qure_careers" / "listing.html"


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
        company_id="qure-ai",
        company_name="Qure.ai",
        status=SourceStatus.REVIEWED,
        careers_url=QURE_CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": QURE_ADAPTER_KEY},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "Date_Opened",
            DateBasis.UNKNOWN,
            False,
            "Zoho Date_Opened is not verified as publication evidence.",
        ),
        detail_strategy=DetailStrategy.LISTING_PAYLOAD,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=("https://jobs.qure.ai/", QURE_CAREERS_URL),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def response(body: bytes, *, final_url: str = "") -> HttpResponse:
    return HttpResponse("", final_url, 200, "text/html", 0, body)


def adapter_for(responses: list[HttpResponse]) -> tuple[QureCareersAdapter, Transport]:
    transport = Transport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return QureCareersAdapter(client), transport


def test_embedded_collection_maps_identity_description_location_and_date_evidence() -> None:
    adapter, transport = adapter_for([response(FIXTURE.read_bytes())])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 1
    assert [job.external_job_id for job in result.jobs] == [
        "102070000000000001",
        "102070000000000002",
    ]
    first, second = result.jobs
    assert first.location_original == "Bengaluru, Karnataka, India"
    assert first.published_at is not None
    assert first.published_at.isoformat() == "2026-09-28"
    assert first.date_basis is DateBasis.UNKNOWN
    assert first.description is not None
    assert "medical-imaging models" in first.description
    assert second.location_original == "Remote, India"
    assert result.diagnostics[-1].category == "unverified_date_opened"
    assert transport.calls == [QURE_CAREERS_URL]


def test_malformed_date_link_mismatch_empty_and_redirect_fail_closed() -> None:
    document = FIXTURE.read_text(encoding="utf-8")
    malformed, _ = adapter_for([response(document.replace("2026-09-28", "today").encode())])
    assert malformed.list_jobs(source()).outcome is AdapterOutcome.FAILED

    mismatch, _ = adapter_for(
        [
            response(
                document.replace("102070000000000002/ML-Platform-Engineer", "999/Other").encode()
            )
        ]
    )
    assert mismatch.list_jobs(source()).outcome is AdapterOutcome.SUSPICIOUS

    empty = document.replace(
        document[document.index("value='") + 7 : document.index("'>", document.index("value='"))],
        "[]",
    )
    empty_adapter, _ = adapter_for([response(empty.encode())])
    assert empty_adapter.list_jobs(source()).outcome is AdapterOutcome.FAILED

    redirected, _ = adapter_for(
        [response(FIXTURE.read_bytes(), final_url="https://example.com/jobs")]
    )
    assert redirected.list_jobs(source()).outcome is AdapterOutcome.FAILED


def test_source_configuration_is_strict() -> None:
    adapter, transport = adapter_for([])
    with pytest.raises(AdapterConfigurationError, match="adapter_key=qure_zoho_embedded"):
        adapter.list_jobs(replace(source(), adapter_parameters={"adapter_key": "other"}))
    with pytest.raises(AdapterConfigurationError, match="requires careers_url"):
        adapter.list_jobs(replace(source(), careers_url="https://jobs.qure.ai/"))
    assert transport.calls == []
