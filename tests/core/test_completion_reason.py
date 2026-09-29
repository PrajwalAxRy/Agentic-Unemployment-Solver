"""Completion-reason classification (to_change.md 6.6, 9.6, prerequisite for 3.4).

``AdapterResult.complete`` was a bare bool conflating "the board is exhausted" with "I hit
my own page cap and stopped looking". Those demand opposite responses from the staleness
logic: a job absent from an exhausted listing is genuinely gone, while a job absent from a
truncated one may simply never have been fetched.

Under the Phase 4 close rule that difference closes live jobs, which is why 6.6 blocks 3.4
rather than being a tidy-up.
"""

from __future__ import annotations

import pytest

from job_finder.adapters.base import classify_completion, list_jobs_with_retry
from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.core.source_contracts import (
    AdapterDiagnostic,
    AdapterOutcome,
    AdapterResult,
    AdapterType,
    CompanySource,
    CompletionReason,
    Confidence,
    DateStrategy,
    DetailStrategy,
    DiagnosticSeverity,
    IdentityStrategy,
    SourceStatus,
)


def _source() -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id="example",
        company_name="Example",
        status=SourceStatus.ENABLED,
        careers_url="https://jobs.example.com",
        adapter_type=AdapterType.GREENHOUSE,
        adapter_parameters={"board_token": "example"},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy("publishedAt", DateBasis.PUBLISHED, True, "test"),
        detail_strategy=DetailStrategy.LISTING_PAYLOAD,
        enabled=True,
        confidence=Confidence.HIGH,
        evidence=("https://jobs.example.com",),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def _job() -> NormalizedJob:
    return NormalizedJob(
        1,
        "example",
        "greenhouse",
        "1",
        "ML Engineer",
        "ml engineer",
        "Bengaluru, India",
        ("bengaluru india",),
        None,
        None,
        DateBasis.UNKNOWN,
        "https://jobs.example.com/1",
    )


def _diagnostic(category: str) -> AdapterDiagnostic:
    return AdapterDiagnostic(
        category=category,
        severity=DiagnosticSeverity.WARNING,
        message=f"{category} occurred",
        context={},
    )


def _result(
    *,
    outcome: AdapterOutcome,
    complete: bool,
    diagnostics: tuple[AdapterDiagnostic, ...] = (),
    jobs: tuple[NormalizedJob, ...] | None = None,
    completion_reason: CompletionReason | None = None,
) -> AdapterResult:
    if jobs is None:
        jobs = (_job(),) if outcome is not AdapterOutcome.EMPTY else ()
    return AdapterResult(
        schema_version=1,
        source=_source(),
        outcome=outcome,
        jobs=jobs,
        page_count=1,
        complete=complete,
        diagnostics=diagnostics,
        completion_reason=completion_reason,
    )


def test_omitted_reason_defaults_to_preserve_existing_meaning() -> None:
    """87 existing call sites pass only ``complete=``; they must keep working."""
    assert _result(outcome=AdapterOutcome.SUCCESS, complete=True).completion_reason is (
        CompletionReason.EXHAUSTED
    )
    truncated = _result(
        outcome=AdapterOutcome.PARTIAL,
        complete=False,
        diagnostics=(_diagnostic("timeout"),),
    )
    assert truncated.completion_reason is CompletionReason.INCOMPLETE


def test_only_exhausted_is_safe_for_absence_counting() -> None:
    """The property that stops silent truncation from closing live jobs (3.4)."""
    assert _result(outcome=AdapterOutcome.SUCCESS, complete=True).safe_for_absence_counting

    for reason in (
        CompletionReason.PAGE_CAP_REACHED,
        CompletionReason.TRUNCATED,
        CompletionReason.INCOMPLETE,
    ):
        result = _result(
            outcome=AdapterOutcome.PARTIAL,
            complete=False,
            diagnostics=(_diagnostic("pagination_limit"),),
            completion_reason=reason,
        )
        assert not result.safe_for_absence_counting, (
            f"{reason.value} must never feed the absence counter: a job missing from such a "
            "run may simply not have been fetched"
        )


def test_page_cap_is_distinguished_from_other_truncation() -> None:
    """The distinction the bare bool could not express.

    Sixteen adapters already recorded ``pagination_limit``; the information existed and was
    discarded at the contract boundary.
    """
    capped = classify_completion(
        _result(
            outcome=AdapterOutcome.SUSPICIOUS,
            complete=False,
            diagnostics=(_diagnostic("pagination_limit"),),
        )
    )
    assert capped.completion_reason is CompletionReason.PAGE_CAP_REACHED

    failed = classify_completion(
        _result(
            outcome=AdapterOutcome.FAILED,
            complete=False,
            diagnostics=(_diagnostic("timeout"),),
            jobs=(),
        )
    )
    assert failed.completion_reason is CompletionReason.TRUNCATED

    # Both are unsafe -- the distinction is diagnostic, not permissive.
    assert not capped.safe_for_absence_counting
    assert not failed.safe_for_absence_counting


def test_classification_does_not_downgrade_an_exhausted_run() -> None:
    complete = classify_completion(_result(outcome=AdapterOutcome.SUCCESS, complete=True))
    assert complete.completion_reason is CompletionReason.EXHAUSTED
    assert complete.safe_for_absence_counting


def test_contradictory_reason_and_complete_flag_are_rejected() -> None:
    """Guard against the two fields drifting apart during migration."""
    with pytest.raises(ValueError, match="only 'exhausted' may be complete"):
        _result(
            outcome=AdapterOutcome.SUCCESS,
            complete=True,
            completion_reason=CompletionReason.PAGE_CAP_REACHED,
        )


class _StubAdapter:
    """Returns a scripted sequence of results."""

    adapter_type = AdapterType.GREENHOUSE

    def __init__(self, results: list[AdapterResult]) -> None:
        self._results = results
        self.call_count = 0

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        self.call_count += 1
        return self._results[min(self.call_count - 1, len(self._results) - 1)]


def test_retry_classifies_the_final_result_and_backs_off() -> None:
    """Retries must delay. Immediate retry amplifies a 429 into a block (9.7)."""
    capped = _result(
        outcome=AdapterOutcome.SUSPICIOUS,
        complete=False,
        diagnostics=(_diagnostic("pagination_limit"),),
    )
    adapter = _StubAdapter([capped])
    delays: list[float] = []

    result, attempts = list_jobs_with_retry(adapter, _source(), retry_count=2, sleep=delays.append)

    assert attempts == 3
    assert len(delays) == 2, "each retry must be preceded by a delay"
    assert all(delay >= 0.0 for delay in delays)
    assert result.completion_reason is CompletionReason.PAGE_CAP_REACHED
    assert not result.safe_for_absence_counting


def test_successful_first_attempt_does_not_sleep() -> None:
    adapter = _StubAdapter([_result(outcome=AdapterOutcome.SUCCESS, complete=True)])
    delays: list[float] = []

    result, attempts = list_jobs_with_retry(adapter, _source(), retry_count=3, sleep=delays.append)

    assert attempts == 1
    assert delays == []
    assert result.safe_for_absence_counting
