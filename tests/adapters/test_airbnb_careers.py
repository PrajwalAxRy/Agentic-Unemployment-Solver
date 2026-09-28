"""Fixture-backed tests for Airbnb's server-rendered careers pages."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.airbnb_careers import (
    AIRBNB_ADAPTER_KEY,
    AIRBNB_CAREERS_URL,
    AirbnbCareersAdapter,
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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "airbnb_careers"


class Transport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **_: object) -> HttpResponse:
        self.calls.append(url)
        response = self.responses.pop(0)
        return replace(response, requested_url=url, final_url=response.final_url or url)

    def post(self, url: str, **_: object) -> HttpResponse:
        self.calls.append(url)
        response = self.responses.pop(0)
        return replace(response, requested_url=url, final_url=response.final_url or url)


def source() -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id="airbnb",
        company_name="Airbnb",
        status=SourceStatus.REVIEWED,
        careers_url=AIRBNB_CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": AIRBNB_ADAPTER_KEY},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            "WebPage.datePublished",
            DateBasis.UNKNOWN,
            False,
            "Detail WebPage date is retained but not verified as job publication evidence.",
        ),
        detail_strategy=DetailStrategy.DETAIL_PAGE,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(AIRBNB_CAREERS_URL,),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def response(name: str, *, final_url: str = "") -> HttpResponse:
    return HttpResponse("", final_url, 200, "text/html", 0, (FIXTURES / name).read_bytes())


def raw_response(body: bytes, *, final_url: str = "") -> HttpResponse:
    return HttpResponse("", final_url, 200, "text/html", 0, body)


def pagination_response(
    name: str,
    *,
    page: int = 2,
    total_rows: int = 11,
    total_pages: int = 2,
) -> HttpResponse:
    payload = {
        "facets": {},
        "template": (FIXTURES / name).read_text(encoding="utf-8"),
        "settings": {
            "pager": {
                "page": page,
                "per_page": 10,
                "total_rows": total_rows,
                "total_pages": total_pages,
            }
        },
    }
    return HttpResponse("", "", 200, "application/json", 0, json.dumps(payload).encode())


def adapter_for(responses: list[HttpResponse]) -> tuple[AirbnbCareersAdapter, Transport]:
    transport = Transport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return AirbnbCareersAdapter(client), transport


def test_pagination_and_deferred_detail_preserve_identity_and_unknown_date() -> None:
    adapter, transport = adapter_for(
        [response("page1.html"), pagination_response("page2.html"), response("detail.html")]
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 2
    assert len(result.jobs) == 11
    first = result.jobs[0]
    assert first.external_job_id == "1001"
    assert first.title_original == "ML Engineer"
    assert first.location_original == "Bengaluru, India"
    assert first.description is None
    assert first.date_basis is DateBasis.UNKNOWN
    assert result.diagnostics[-1].category == "unverified_webpage_date_requires_detail"

    detailed = adapter.get_job_detail(source(), first)
    assert detailed.description is not None
    assert "machine-learning systems" in detailed.description
    assert detailed.published_at is not None
    assert detailed.published_at.isoformat() == "2026-09-28"
    assert detailed.date_basis is DateBasis.UNKNOWN
    assert transport.calls == [
        AIRBNB_CAREERS_URL,
        "https://careers.airbnb.com/positions/?_paged=2",
        first.canonical_url,
    ]


def test_changed_total_duplicate_and_redirect_fail_closed() -> None:
    page2 = (FIXTURES / "page2.html").read_text(encoding="utf-8")
    changed, _ = adapter_for(
        [response("page1.html"), pagination_response("page2.html", total_rows=12)]
    )
    assert changed.list_jobs(source()).outcome is AdapterOutcome.PARTIAL

    duplicate, _ = adapter_for(
        [
            response("page1.html"),
            HttpResponse(
                "",
                "",
                200,
                "application/json",
                0,
                json.dumps(
                    {
                        "template": page2.replace("1011", "1001"),
                        "settings": {
                            "pager": {
                                "page": 2,
                                "per_page": 10,
                                "total_rows": 11,
                                "total_pages": 2,
                            }
                        },
                    }
                ).encode(),
            ),
        ]
    )
    assert duplicate.list_jobs(source()).outcome is AdapterOutcome.SUSPICIOUS

    redirected, _ = adapter_for(
        [response("page1.html", final_url="https://example.com/positions/")]
    )
    assert redirected.list_jobs(source()).outcome is AdapterOutcome.FAILED


def test_detail_schema_and_source_configuration_are_strict() -> None:
    adapter, _ = adapter_for([response("page1.html"), pagination_response("page2.html")])
    job = adapter.list_jobs(source()).jobs[0]
    detail = (FIXTURES / "detail.html").read_text(encoding="utf-8")
    broken, _ = adapter_for([raw_response(detail.replace("Bengaluru, India", "London").encode())])
    with pytest.raises(ValueError, match="location does not match"):
        broken.get_job_detail(source(), job)

    configured, transport = adapter_for([])
    with pytest.raises(AdapterConfigurationError, match="adapter_key=airbnb_careers_pages"):
        configured.list_jobs(replace(source(), adapter_parameters={"adapter_key": "other"}))
    with pytest.raises(AdapterConfigurationError, match="requires careers_url"):
        configured.list_jobs(replace(source(), careers_url="https://careers.airbnb.com/positions"))
    assert transport.calls == []
