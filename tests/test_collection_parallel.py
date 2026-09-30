"""Parallel source collection (to_change.md 6.5, 9.8).

The scan was fully sequential: 150 companies / 3,108s is ~20.7s per company, essentially
all blocking I/O, and 330 companies would be ~114 minutes.

Two properties matter more than the speedup, and both are easy to get silently wrong:

* **Exceptions must not vanish.** A thread pool swallows them more thoroughly than a bare
  ``except`` -- an unretrieved ``Future`` discards its exception without a trace. That is
  the failure mode Phase 0 existed to eliminate, which is why 6.5 is sequenced after it.
* **Output must not depend on completion order.** The report has to be identical whether
  the pool is used or not, or every downstream diff becomes unreadable.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_finder.adapters.connectivity import ConnectivityPolicy, ConnectivityWaiter
from job_finder.collection import collect_listings
from job_finder.core.company_registry import CompanyRegistryEntry, CompanySourceRegistry
from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.core.search_profile import load_search_profile
from job_finder.core.source_contracts import (
    AdapterDiagnostic,
    AdapterOutcome,
    AdapterResult,
    AdapterType,
    CompanySource,
    Confidence,
    DateStrategy,
    DetailStrategy,
    DiagnosticSeverity,
    IdentityStrategy,
    SourceStatus,
)

ROOT = Path(__file__).resolve().parents[1]


def _source(company_id: str) -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id=company_id,
        company_name=company_id.title(),
        status=SourceStatus.ENABLED,
        careers_url=f"https://jobs.{company_id}.com",
        adapter_type=AdapterType.GREENHOUSE,
        adapter_parameters={"board_token": company_id},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy("publishedAt", DateBasis.PUBLISHED, True, "test"),
        detail_strategy=DetailStrategy.LISTING_PAYLOAD,
        enabled=True,
        confidence=Confidence.HIGH,
        evidence=(f"https://jobs.{company_id}.com",),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def _registry(count: int) -> CompanySourceRegistry:
    entries = tuple(
        CompanyRegistryEntry(
            source_rank=index,
            priority="p1",
            last_verified_at=None,
            source=_source(f"company{index:02d}"),
        )
        for index in range(1, count + 1)
    )
    return CompanySourceRegistry(
        schema_version=1,
        registry_version="test",
        generated_at=datetime(2026, 9, 30, tzinfo=UTC),
        discovery_batch_id="test",
        entries=entries,
    )


def _job(source: CompanySource, index: int) -> NormalizedJob:
    return NormalizedJob(
        1,
        source.company_id,
        source.adapter_type.value,
        f"{source.company_id}-{index}",
        "Machine Learning Engineer",
        "machine learning engineer",
        "Bengaluru, India",
        ("bengaluru india",),
        None,
        None,
        DateBasis.UNKNOWN,
        f"https://jobs.{source.company_id}.com/{index}",
    )


class _SlowAdapter:
    """Sleeps briefly so that true concurrency is observable."""

    adapter_type = AdapterType.GREENHOUSE

    def __init__(self, *, delay: float = 0.05, failing: set[str] | None = None) -> None:
        self._delay = delay
        self._failing = failing or set()
        self.active = 0
        self.peak = 0
        self._guard = threading.Lock()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        with self._guard:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            threading.Event().wait(self._delay)
            if source.company_id in self._failing:
                raise RuntimeError(f"adapter exploded for {source.company_id}")
            return AdapterResult(
                schema_version=1,
                source=source,
                outcome=AdapterOutcome.SUCCESS,
                jobs=(_job(source, 1),),
                page_count=1,
                complete=True,
                diagnostics=(),
            )
        finally:
            with self._guard:
                self.active -= 1


class _Registry:
    def __init__(self, adapter: _SlowAdapter) -> None:
        self._adapter = adapter

    def resolve(self, source: CompanySource) -> _SlowAdapter:
        return self._adapter


def _collect(registry: CompanySourceRegistry, adapter: _SlowAdapter, *, max_workers: int):
    return collect_listings(
        registry,
        _Registry(adapter),
        load_search_profile(ROOT / "config" / "search_profile.toml"),
        source_retry_count=0,
        max_workers=max_workers,
    )


def test_parallel_and_sequential_reports_are_identical() -> None:
    """Determinism is the precondition for using the pool at all."""
    registry = _registry(8)

    sequential = _collect(registry, _SlowAdapter(delay=0.0), max_workers=1)
    parallel = _collect(registry, _SlowAdapter(delay=0.01), max_workers=4)

    assert [company.company_id for company in parallel.companies] == [
        company.company_id for company in sequential.companies
    ]
    assert [company.source_rank for company in parallel.companies] == sorted(
        company.source_rank for company in parallel.companies
    ), "results must be ordered by source_rank, not by completion order"
    assert parallel.listing_count == sequential.listing_count

    # Compare everything except duration_seconds: wall-clock timing legitimately differs
    # between a sequential and a parallel run, and that is the one field expected to.
    def _without_timing(report: object) -> list[dict[str, object]]:
        return [
            {k: v for k, v in company.items() if k != "duration_seconds"}
            for company in report.as_json()["companies"]  # type: ignore[attr-defined,union-attr]
        ]

    assert _without_timing(parallel) == _without_timing(sequential)


def test_companies_are_actually_fetched_concurrently() -> None:
    adapter = _SlowAdapter(delay=0.05)

    _collect(_registry(8), adapter, max_workers=4)

    assert adapter.peak > 1, "expected overlapping fetches; the pool is not doing anything"
    assert adapter.peak <= 4, f"exceeded the worker cap: {adapter.peak}"


def test_worker_exceptions_are_reraised_not_swallowed() -> None:
    """The 9.8 trap: an unretrieved Future discards its exception silently."""
    adapter = _SlowAdapter(delay=0.0, failing={"company03"})

    with pytest.raises(RuntimeError, match="adapter exploded for company03"):
        _collect(_registry(5), adapter, max_workers=4)


def test_sequential_path_remains_the_default() -> None:
    """max_workers defaults to 1, so behaviour is unchanged unless a caller opts in."""
    adapter = _SlowAdapter(delay=0.01)

    collect_listings(
        _registry(4),
        _Registry(adapter),
        load_search_profile(ROOT / "config" / "search_profile.toml"),
        source_retry_count=0,
    )

    assert adapter.peak == 1, "default collection must remain fully sequential"


def test_progress_callback_reports_every_company_exactly_once() -> None:
    """The callback is not thread-safe; it is called under a lock."""
    messages: list[str] = []
    adapter = _SlowAdapter(delay=0.01)

    collect_listings(
        _registry(10),
        _Registry(adapter),
        load_search_profile(ROOT / "config" / "search_profile.toml"),
        source_retry_count=0,
        progress=messages.append,
        max_workers=5,
    )

    collection_messages = [item for item in messages if "phase=source_collection" in item]
    assert len(collection_messages) == 10
    counters = [item.split("progress=")[1].split()[0] for item in collection_messages]
    assert sorted(counters, key=lambda value: int(value.split("/")[0])) == [
        f"{index}/10" for index in range(1, 11)
    ], f"progress counter skipped or repeated a value: {counters}"


class _NetworkFailureAdapter:
    """Fails every company with a chosen diagnostic category."""

    adapter_type = AdapterType.GREENHOUSE

    def __init__(self, category: str) -> None:
        self._category = category
        self.calls = 0

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        self.calls += 1
        return AdapterResult(
            schema_version=1,
            source=source,
            outcome=AdapterOutcome.FAILED,
            jobs=(),
            page_count=0,
            complete=False,
            diagnostics=(
                AdapterDiagnostic(
                    category=self._category,
                    severity=DiagnosticSeverity.ERROR,
                    message=f"{self._category} occurred",
                    context={},
                ),
            ),
        )


def _collect_with_waiter(adapter: object, waiter: ConnectivityWaiter, count: int = 5):
    return collect_listings(
        _registry(count),
        _Registry(adapter),  # type: ignore[arg-type]
        load_search_profile(ROOT / "config" / "search_profile.toml"),
        source_retry_count=0,
        waiter=waiter,
    )


def test_repeated_network_failures_pause_the_scan_and_retry() -> None:
    """The failure this exists to prevent: a dropped connection wasting a whole run.

    HttpPolicy's retry budget is about 1.5 seconds, which is right for a flaky request and
    useless for a dead link -- without this, the remaining companies all fail in seconds.
    """
    adapter = _NetworkFailureAdapter("network_error")
    slept: list[float] = []
    waiter = ConnectivityWaiter(
        policy=ConnectivityPolicy(poll_interval_seconds=1.0, max_wait_seconds=10.0),
        sleep=slept.append,
        check=lambda: len(slept) >= 1,  # network returns after one poll
    )

    _collect_with_waiter(adapter, waiter)

    assert waiter.total_waits >= 1, "an outage should have been detected"
    assert slept, "the scan should have paused and polled"
    # Every paused company is retried once the network is back, so the run is not wasted.
    assert adapter.calls > 5


def test_http_errors_never_pause_the_scan() -> None:
    """The boundary that matters most.

    A 500 or a 429 means the server was reached and is unhappy -- a different problem with
    a different remedy. Pausing the whole scan for one unhappy site would be far worse
    than the failure itself.
    """
    adapter = _NetworkFailureAdapter("http_error")
    waiter = ConnectivityWaiter(
        policy=ConnectivityPolicy(poll_interval_seconds=1.0, max_wait_seconds=10.0),
        sleep=lambda _: pytest.fail("an HTTP error must not pause the scan"),
        check=lambda: pytest.fail("an HTTP error must not trigger a probe"),  # type: ignore[arg-type,return-value]
    )

    _collect_with_waiter(adapter, waiter)

    assert waiter.total_waits == 0
    assert adapter.calls == 5, "each company attempted exactly once"


def test_collection_without_a_waiter_is_unchanged() -> None:
    """Opt-in: omitting the waiter preserves the previous behaviour exactly."""
    adapter = _NetworkFailureAdapter("network_error")

    report = collect_listings(
        _registry(3),
        _Registry(adapter),  # type: ignore[arg-type]
        load_search_profile(ROOT / "config" / "search_profile.toml"),
        source_retry_count=0,
    )

    assert adapter.calls == 3
    assert report.healthy is False
