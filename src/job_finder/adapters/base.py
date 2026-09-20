"""Runtime interface and registry shared by all job-source adapters."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol

from job_finder.adapters.http_client import HttpRequestError
from job_finder.core.source_contracts import (
    AdapterDiagnostic,
    AdapterResult,
    AdapterType,
    CompanySource,
    DiagnosticSeverity,
)


class AdapterConfigurationError(ValueError):
    """A source cannot be handled by the selected adapter."""


class JobSourceAdapter(Protocol):
    """Common listing operation implemented by every adapter family."""

    @property
    def adapter_type(self) -> AdapterType: ...

    def list_jobs(self, source: CompanySource) -> AdapterResult: ...


class AdapterRegistry:
    """Explicit adapter lookup that rejects missing or duplicate implementations."""

    def __init__(self, adapters: Iterable[JobSourceAdapter] = ()) -> None:
        self._adapters: dict[AdapterType, JobSourceAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: JobSourceAdapter) -> None:
        if adapter.adapter_type in self._adapters:
            raise AdapterConfigurationError(
                f"adapter already registered: {adapter.adapter_type.value}"
            )
        self._adapters[adapter.adapter_type] = adapter

    def resolve(self, source: CompanySource) -> JobSourceAdapter:
        adapter = self._adapters.get(source.adapter_type)
        if adapter is None:
            raise AdapterConfigurationError(
                f"no adapter registered for source type: {source.adapter_type.value}"
            )
        return adapter

    @property
    def adapter_types(self) -> tuple[AdapterType, ...]:
        return tuple(sorted(self._adapters, key=lambda item: item.value))


def require_source_configuration(
    source: CompanySource,
    *,
    adapter_type: AdapterType,
    required_parameters: Iterable[str],
) -> Mapping[str, str]:
    """Validate family and runtime parameters before issuing a network request."""
    if source.adapter_type is not adapter_type:
        raise AdapterConfigurationError(
            f"adapter {adapter_type.value} cannot handle source type {source.adapter_type.value}"
        )
    missing = [name for name in required_parameters if not source.adapter_parameters.get(name)]
    if missing:
        raise AdapterConfigurationError(
            f"adapter {adapter_type.value} requires parameters: {', '.join(missing)}"
        )
    return source.adapter_parameters


def request_failure_diagnostic(error: HttpRequestError) -> AdapterDiagnostic:
    """Convert a bounded HTTP failure into a body-free adapter diagnostic."""
    context = {"retryable": str(error.retryable).lower()}
    if error.status_code is not None:
        context["status_code"] = str(error.status_code)
    return AdapterDiagnostic(
        category=error.category.value,
        severity=DiagnosticSeverity.ERROR,
        message=str(error),
        context=context,
    )
