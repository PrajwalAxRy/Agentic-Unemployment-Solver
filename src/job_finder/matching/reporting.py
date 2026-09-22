"""Sanitized aggregate request and token reporting for LLM evaluation runs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from job_finder.matching.evaluator import EvaluationDisposition, EvaluationOutcome


@dataclass(frozen=True, slots=True)
class LLMUsageReport:
    """Aggregate outcome and token counts without prompts or job descriptions."""

    evaluated_job_count: int
    completed_count: int
    manual_review_count: int
    match_count: int
    rejection_count: int
    uncertain_count: int
    retry_count: int
    response_error_count: int
    request_count: int
    estimated_input_tokens: int
    measured_input_tokens: int
    measured_output_tokens: int
    prompt_versions: tuple[str, ...]
    model_policies: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        """Return a stable JSON-compatible representation."""
        return asdict(self)


def summarize_usage(outcomes: tuple[EvaluationOutcome, ...]) -> LLMUsageReport:
    """Aggregate per-evaluation deltas without exposing evaluated content."""
    completed = tuple(
        outcome for outcome in outcomes if outcome.disposition is EvaluationDisposition.COMPLETED
    )
    decisions = tuple(outcome.decision for outcome in completed if outcome.decision is not None)
    return LLMUsageReport(
        evaluated_job_count=len(outcomes),
        completed_count=len(completed),
        manual_review_count=len(outcomes) - len(completed),
        match_count=sum(decision.seniority_match is True for decision in decisions),
        rejection_count=sum(decision.seniority_match is False for decision in decisions),
        uncertain_count=sum(decision.seniority_match == "uncertain" for decision in decisions),
        retry_count=sum(max(outcome.attempt_count - 1, 0) for outcome in outcomes),
        response_error_count=sum(len(outcome.errors) for outcome in outcomes),
        request_count=sum(outcome.usage.request_count for outcome in outcomes),
        estimated_input_tokens=sum(outcome.usage.estimated_input_tokens for outcome in outcomes),
        measured_input_tokens=sum(outcome.usage.measured_input_tokens for outcome in outcomes),
        measured_output_tokens=sum(outcome.usage.measured_output_tokens for outcome in outcomes),
        prompt_versions=tuple(sorted({outcome.prompt_version for outcome in outcomes})),
        model_policies=tuple(sorted({outcome.model_policy for outcome in outcomes})),
    )


def write_usage_report(report: LLMUsageReport, path: Path) -> None:
    """Write a sanitized aggregate report, creating only its parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.as_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
