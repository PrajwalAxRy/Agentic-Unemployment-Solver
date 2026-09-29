"""Runtime interface and registry shared by all job-source adapters."""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from typing import Protocol, runtime_checkable

from job_finder.adapters.http_client import HttpRequestError
from job_finder.core.job_contracts import NormalizedJob
from job_finder.core.source_contracts import (
    AdapterDiagnostic,
    AdapterOutcome,
    AdapterResult,
    AdapterType,
    CompanySource,
    CompletionReason,
    DiagnosticSeverity,
)


class AdapterConfigurationError(ValueError):
    """A source cannot be handled by the selected adapter."""


class JobSourceAdapter(Protocol):
    """Common listing operation implemented by every adapter family."""

    @property
    def adapter_type(self) -> AdapterType: ...

    def list_jobs(self, source: CompanySource) -> AdapterResult: ...


@runtime_checkable
class JobDetailAdapter(Protocol):
    """Optional capability for sources whose list payload omits full details."""

    def get_job_detail(self, source: CompanySource, job: NormalizedJob) -> NormalizedJob: ...


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


_PAGE_CAP_DIAGNOSTIC_CATEGORIES = frozenset({"pagination_limit"})

_RETRY_BASE_DELAY_SECONDS = 1.0
_RETRY_MAX_DELAY_SECONDS = 30.0


def classify_completion(result: AdapterResult) -> AdapterResult:
    """Attach a specific :class:`CompletionReason` where the adapter implied one.

    Sixteen adapters already record a ``pagination_limit`` diagnostic when they stop at
    their own page cap -- the information existed, but ``complete: bool`` had no way to
    express it, so it was discarded at the contract boundary (``to_change.md`` 6.6).

    Applied centrally rather than by editing sixteen adapters, so nothing depends on each
    adapter remembering to classify itself. Adapters that already set ``completion_reason``
    explicitly are left alone.
    """
    if result.completion_reason not in (None, CompletionReason.INCOMPLETE):
        return result
    if result.complete:
        return result
    hit_page_cap = any(
        diagnostic.category in _PAGE_CAP_DIAGNOSTIC_CATEGORIES for diagnostic in result.diagnostics
    )
    reason = CompletionReason.PAGE_CAP_REACHED if hit_page_cap else CompletionReason.TRUNCATED
    return replace(result, completion_reason=reason)


def list_jobs_with_retry(
    adapter: JobSourceAdapter,
    source: CompanySource,
    *,
    retry_count: int,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[AdapterResult, int]:
    """Retry incomplete whole-source scans without retrying empty or blocked results.

    Retries back off exponentially with jitter. Previously they fired immediately with no
    delay, which turns a 429 into a block -- the remote end sees a burst rather than a
    client that respects it (``to_change.md`` 6.6, 9.7). ``Retry-After`` is honoured
    centrally in the transport; this is the outer, whole-source retry.
    """
    if retry_count < 0:
        raise ValueError("retry_count cannot be negative")
    retryable_outcomes = {
        AdapterOutcome.PARTIAL,
        AdapterOutcome.FAILED,
        AdapterOutcome.SUSPICIOUS,
    }
    result = adapter.list_jobs(source)
    attempt_count = 1
    while result.outcome in retryable_outcomes and attempt_count <= retry_count:
        delay = min(
            _RETRY_BASE_DELAY_SECONDS * (2 ** (attempt_count - 1)), _RETRY_MAX_DELAY_SECONDS
        )
        # Full jitter: spreads retries when many companies fail at once, e.g. a shared
        # ATS host having a bad minute.
        sleep(random.uniform(0.0, delay))
        result = adapter.list_jobs(source)
        attempt_count += 1
    return classify_completion(result), attempt_count


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
