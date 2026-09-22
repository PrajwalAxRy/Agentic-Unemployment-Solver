"""Cache-aware boundary between deterministic filtering and LLM evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from job_finder.core.job_contracts import NormalizedJob
from job_finder.matching.evaluator import (
    EvaluationDisposition,
    EvaluationOutcome,
    SeniorityEvaluator,
)
from job_finder.matching.seniority import SeniorityDecision, seniority_decision_from_mapping
from job_finder.persistence.repository import JobRecord, JobStateRepository


class CandidateEligibility(StrEnum):
    """Deterministic result that controls whether the LLM may be called."""

    ELIGIBLE = "eligible"
    OLD_LISTING = "old_listing"
    ROLE_REJECTED = "role_rejected"
    LOCATION_REJECTED = "location_rejected"


class CachedEvaluationDisposition(StrEnum):
    """Cache/evaluation action taken for one listing."""

    SKIPPED = "skipped"
    CACHED = "cached"
    EVALUATED = "evaluated"
    MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True, slots=True)
class CachedEvaluationResult:
    """Decision plus durable state for one cache-aware evaluation attempt."""

    disposition: CachedEvaluationDisposition
    eligibility: CandidateEligibility
    decision: SeniorityDecision | None
    record: JobRecord | None
    evaluation: EvaluationOutcome | None


class CachedSeniorityEvaluationService:
    """Skip ineligible jobs and persist/reuse validated seniority decisions."""

    def __init__(
        self,
        *,
        repository: JobStateRepository,
        evaluator: SeniorityEvaluator,
    ) -> None:
        self._repository = repository
        self._evaluator = evaluator

    def evaluate(
        self,
        job: NormalizedJob,
        *,
        eligibility: CandidateEligibility,
        profile_version: str,
        target_description: str,
    ) -> CachedEvaluationResult:
        """Evaluate only eligible detailed jobs, preserving cache and manual-review state."""
        if eligibility is not CandidateEligibility.ELIGIBLE:
            return CachedEvaluationResult(
                disposition=CachedEvaluationDisposition.SKIPPED,
                eligibility=eligibility,
                decision=None,
                record=None,
                evaluation=None,
            )

        preparation = self._repository.prepare_evaluation(
            job,
            profile_version=profile_version,
            prompt_version=self._evaluator.prompt_version,
            model_policy=self._evaluator.model_policy,
        )
        if not preparation.needs_evaluation:
            if preparation.record.seniority_result is None:
                raise ValueError("completed cached evaluation is missing its seniority result")
            return CachedEvaluationResult(
                disposition=CachedEvaluationDisposition.CACHED,
                eligibility=eligibility,
                decision=seniority_decision_from_mapping(preparation.record.seniority_result),
                record=preparation.record,
                evaluation=None,
            )

        if job.description is None:
            raise ValueError("eligible evaluation requires a job description")
        outcome = self._evaluator.evaluate(
            title=job.title_original,
            description=job.description,
            target_description=target_description,
        )
        if outcome.disposition is EvaluationDisposition.MANUAL_REVIEW:
            return CachedEvaluationResult(
                disposition=CachedEvaluationDisposition.MANUAL_REVIEW,
                eligibility=eligibility,
                decision=None,
                record=preparation.record,
                evaluation=outcome,
            )

        if outcome.decision is None:
            raise AssertionError("completed evaluation must contain a decision")
        record = self._repository.complete_evaluation(
            preparation.record.job_key,
            outcome.decision.as_json(),
        )
        return CachedEvaluationResult(
            disposition=CachedEvaluationDisposition.EVALUATED,
            eligibility=eligibility,
            decision=outcome.decision,
            record=record,
            evaluation=outcome,
        )
