"""Tests for sanitized aggregate LLM usage reporting."""

from __future__ import annotations

import json
from pathlib import Path

from job_finder.matching.evaluator import (
    EvaluationDisposition,
    EvaluationOutcome,
    UsageSnapshot,
)
from job_finder.matching.reporting import summarize_usage, write_usage_report
from job_finder.matching.seniority import DetectedLevel, SeniorityDecision


def outcome(
    match: bool | str | None,
    *,
    attempts: int = 1,
    errors: tuple[str, ...] = (),
) -> EvaluationOutcome:
    decision = (
        SeniorityDecision(
            seniority_match=match,
            detected_level=DetectedLevel.MID,
            required_experience="3+ years",
            evidence="3+ years required",
            reason="Compared with target.",
        )
        if match is not None
        else None
    )
    return EvaluationOutcome(
        disposition=(
            EvaluationDisposition.COMPLETED
            if decision is not None
            else EvaluationDisposition.MANUAL_REVIEW
        ),
        decision=decision,
        attempt_count=attempts,
        errors=errors,
        usage=UsageSnapshot(
            request_count=attempts,
            estimated_input_tokens=100 * attempts,
            measured_input_tokens=90 * attempts,
            measured_output_tokens=20 * attempts,
        ),
        prompt_version="1.0.0",
        model_policy="test:stub:1",
    )


def test_usage_summary_counts_outcomes_retries_and_tokens() -> None:
    report = summarize_usage(
        (
            outcome(True),
            outcome(False),
            outcome("uncertain", attempts=2, errors=("invalid JSON",)),
            outcome(None, attempts=2, errors=("invalid JSON", "invalid JSON")),
        )
    )

    assert report.evaluated_job_count == 4
    assert report.completed_count == 3
    assert report.manual_review_count == 1
    assert (report.match_count, report.rejection_count, report.uncertain_count) == (1, 1, 1)
    assert report.retry_count == 2
    assert report.response_error_count == 3
    assert report.request_count == 6
    assert report.measured_input_tokens == 540
    assert report.measured_output_tokens == 120
    assert report.prompt_versions == ("1.0.0",)
    assert report.model_policies == ("test:stub:1",)


def test_usage_report_contains_no_prompt_or_job_content(tmp_path: Path) -> None:
    report = summarize_usage((outcome(True),))
    path = tmp_path / "reports" / "usage.json"

    write_usage_report(report, path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["request_count"] == 1
    assert "prompt" not in payload
    assert "description" not in payload
    assert "evidence" not in payload
