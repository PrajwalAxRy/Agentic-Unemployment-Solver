"""Tests for the shared adapter interface and registry."""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from job_finder.adapters.base import (
    AdapterConfigurationError,
    AdapterRegistry,
    JobSourceAdapter,
    request_failure_diagnostic,
    require_source_configuration,
)
from job_finder.adapters.http_client import HttpFailureCategory, HttpRequestError
from job_finder.core.job_contracts import DateBasis
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


def source(adapter_type: AdapterType = AdapterType.ASHBY) -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id="example",
        company_name="Example",
        status=SourceStatus.REVIEWED,
        careers_url="https://jobs.example.com",
        adapter_type=adapter_type,
        adapter_parameters={"board_name": "example"},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            field_name="publishedAt",
            basis=DateBasis.PUBLISHED,
            verified_as_publication=False,
            notes="Requires live verification.",
        ),
        detail_strategy=DetailStrategy.LISTING_PAYLOAD,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=("https://jobs.example.com",),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


@dataclass(frozen=True)
class StubAdapter:
    adapter_type: AdapterType

    def list_jobs(self, company_source: CompanySource) -> AdapterResult:
        return AdapterResult(
            schema_version=1,
            source=company_source,
            outcome=AdapterOutcome.EMPTY,
            jobs=(),
            page_count=1,
            complete=True,
            diagnostics=(),
        )


def test_adapter_implements_runtime_protocol() -> None:
    adapter: JobSourceAdapter = StubAdapter(AdapterType.ASHBY)

    assert adapter.list_jobs(source()).outcome is AdapterOutcome.EMPTY


def test_registry_resolves_by_configured_source_type() -> None:
    ashby = StubAdapter(AdapterType.ASHBY)
    registry = AdapterRegistry([ashby])

    assert registry.resolve(source()) is ashby
    assert registry.adapter_types == (AdapterType.ASHBY,)


def test_registry_rejects_duplicate_and_missing_adapters() -> None:
    registry = AdapterRegistry([StubAdapter(AdapterType.ASHBY)])

    with pytest.raises(AdapterConfigurationError, match="already registered"):
        registry.register(StubAdapter(AdapterType.ASHBY))
    with pytest.raises(AdapterConfigurationError, match="no adapter registered"):
        registry.resolve(source(AdapterType.GREENHOUSE))


def test_source_configuration_rejects_wrong_family_or_missing_parameter() -> None:
    with pytest.raises(AdapterConfigurationError, match="cannot handle"):
        require_source_configuration(
            source(AdapterType.GREENHOUSE),
            adapter_type=AdapterType.ASHBY,
            required_parameters=("board_name",),
        )

    missing = replace(source(), adapter_parameters={})
    with pytest.raises(AdapterConfigurationError, match="requires parameters"):
        require_source_configuration(
            missing,
            adapter_type=AdapterType.ASHBY,
            required_parameters=("board_name",),
        )


def test_http_failure_becomes_sanitized_adapter_diagnostic() -> None:
    error = HttpRequestError(
        HttpFailureCategory.ACCESS_BLOCK,
        "HTTP 403",
        status_code=403,
        retryable=False,
    )

    diagnostic = request_failure_diagnostic(error)

    assert diagnostic.category == "access_block"
    assert diagnostic.message == "HTTP 403"
    assert diagnostic.context == {"retryable": "false", "status_code": "403"}
