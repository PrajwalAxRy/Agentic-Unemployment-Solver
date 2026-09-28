"""Keyed dispatch for independently tested company-specific adapters."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Protocol

from job_finder.adapters.base import (
    AdapterConfigurationError,
    JobDetailAdapter,
    require_source_configuration,
)
from job_finder.core.job_contracts import NormalizedJob
from job_finder.core.source_contracts import AdapterResult, AdapterType, CompanySource

_ADAPTER_KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]*")


class CustomSourceAdapter(Protocol):
    """A custom implementation selected by a stable registry adapter key."""

    adapter_type: AdapterType
    adapter_key: str

    def list_jobs(self, source: CompanySource) -> AdapterResult: ...


class CustomAdapterRouter:
    """Route one `custom` source to exactly one keyed implementation."""

    adapter_type = AdapterType.CUSTOM

    def __init__(self, adapters: Iterable[CustomSourceAdapter] = ()) -> None:
        self._adapters: dict[str, CustomSourceAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: CustomSourceAdapter) -> None:
        if adapter.adapter_type is not AdapterType.CUSTOM:
            raise AdapterConfigurationError(
                "custom router can register only adapter_type=custom implementations"
            )
        key = adapter.adapter_key.strip()
        if not _ADAPTER_KEY_PATTERN.fullmatch(key):
            raise AdapterConfigurationError(
                "custom adapter_key must use lowercase letters, digits, and underscores"
            )
        if key in self._adapters:
            raise AdapterConfigurationError(f"custom adapter already registered: {key}")
        self._adapters[key] = adapter

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        return self._resolve(source).list_jobs(source)

    def get_job_detail(self, source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        """Route deferred detail retrieval through the same source adapter key."""
        adapter = self._resolve(source)
        if not isinstance(adapter, JobDetailAdapter):
            raise AdapterConfigurationError(
                f"custom adapter does not support detail retrieval: {adapter.adapter_key}"
            )
        return adapter.get_job_detail(source, job)

    def _resolve(self, source: CompanySource) -> CustomSourceAdapter:
        parameters = require_source_configuration(
            source,
            adapter_type=AdapterType.CUSTOM,
            required_parameters=("adapter_key",),
        )
        key = parameters["adapter_key"].strip()
        adapter = self._adapters.get(key)
        if adapter is None:
            raise AdapterConfigurationError(f"no custom adapter registered for key: {key}")
        return adapter

    @property
    def adapter_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))
