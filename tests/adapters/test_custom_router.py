"""Tests for deterministic dispatch among company-specific custom adapters."""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from job_finder.adapters.base import AdapterConfigurationError
from job_finder.adapters.custom import CustomAdapterRouter
from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.core.source_contracts import (
    AdapterOutcome,
    AdapterResult,
    AdapterType,
    CompanySource,
    Confidence,
    DateStrategy,
    DetailStrategy,
    IdentityStrategy,
    SourceStatus,
)


def source(adapter_key: str = "alpha") -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id="example",
        company_name="Example",
        status=SourceStatus.REVIEWED,
        careers_url="https://example.com/careers",
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": adapter_key},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(None, DateBasis.UNKNOWN, False, "No public date."),
        detail_strategy=DetailStrategy.DETAIL_PAGE,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=("https://example.com/careers",),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def listing() -> NormalizedJob:
    return NormalizedJob(
        schema_version=1,
        company_id="example",
        source_type="custom",
        external_job_id="job-1",
        title_original="ML Engineer",
        title_normalized="ml engineer",
        location_original="Bengaluru, India",
        location_normalized=("bengaluru", "india"),
        published_at=None,
        published_at_raw=None,
        date_basis=DateBasis.UNKNOWN,
        canonical_url="https://example.com/careers/job-1",
    )


@dataclass
class StubCustomAdapter:
    adapter_key: str
    list_calls: int = 0
    detail_calls: int = 0
    adapter_type: AdapterType = AdapterType.CUSTOM

    def list_jobs(self, company_source: CompanySource) -> AdapterResult:
        self.list_calls += 1
        return AdapterResult(
            schema_version=1,
            source=company_source,
            outcome=AdapterOutcome.EMPTY,
            jobs=(),
            page_count=1,
            complete=True,
            diagnostics=(),
        )

    def get_job_detail(self, company_source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        del company_source
        self.detail_calls += 1
        return replace(job, description=f"detail from {self.adapter_key}")


def test_router_dispatches_listing_and_detail_by_exact_adapter_key() -> None:
    alpha = StubCustomAdapter("alpha")
    beta = StubCustomAdapter("beta")
    router = CustomAdapterRouter([alpha, beta])

    result = router.list_jobs(source("beta"))
    detailed = router.get_job_detail(source("beta"), listing())

    assert result.outcome is AdapterOutcome.EMPTY
    assert alpha.list_calls == 0
    assert beta.list_calls == 1
    assert alpha.detail_calls == 0
    assert beta.detail_calls == 1
    assert detailed.description == "detail from beta"
    assert router.adapter_keys == ("alpha", "beta")


def test_router_rejects_duplicate_unknown_missing_and_non_custom_sources() -> None:
    with pytest.raises(AdapterConfigurationError, match="already registered"):
        CustomAdapterRouter([StubCustomAdapter("alpha"), StubCustomAdapter("alpha")])

    router = CustomAdapterRouter([StubCustomAdapter("alpha")])
    with pytest.raises(AdapterConfigurationError, match="no custom adapter registered"):
        router.list_jobs(source("unknown"))
    with pytest.raises(AdapterConfigurationError, match="requires parameters"):
        router.list_jobs(replace(source(), adapter_parameters={}))
    with pytest.raises(AdapterConfigurationError, match="cannot handle source type"):
        router.list_jobs(replace(source(), adapter_type=AdapterType.ASHBY))
