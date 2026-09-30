"""Evaluator for the merged relevance + seniority + location call (to_change.md 2.5).

Deliberately mirrors :class:`~job_finder.matching.evaluator.SeniorityEvaluator`'s public
surface -- same ``evaluate()`` signature, same ``prompt_version`` / ``model_policy`` /
``usage`` properties, same :class:`EvaluationOutcome` return type. That is what lets the
cache service, the repository and ``scan.py`` consume it without change, and it is what
keeps ``config/seniority_prompt.toml`` switchable as a fallback: the two evaluators are
interchangeable at the call site.

The relevance verdict is the piece that did not exist before. It matters more than it
looks, because 2.2a widened the title filter from an 11% pass rate to roughly 70%: without
a relevance gate behind it, every engineering title in India reaches the report. Title
decides discipline; this decides domain.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from job_finder.matching.evaluator import (
    EvaluationDisposition,
    EvaluationOutcome,
    LLMRequest,
    ModelPolicy,
    UsageBudget,
    UsageLimitExceeded,
    UsageSnapshot,
    _usage_delta,
)
from job_finder.matching.merged_prompt import (
    MergedJudgment,
    MergedPrompt,
    MergedResponseError,
    parse_merged_response,
)
from job_finder.matching.relevance_set import RelevanceVerdict
from job_finder.matching.seniority import SeniorityDecision

_LOGGER = logging.getLogger(__name__)

MERGED_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "relevance",
        "relevance_evidence",
        "relevance_reason",
        "seniority_match",
        "detected_level",
        "required_experience",
        "seniority_evidence",
        "seniority_reason",
    ],
    "properties": {
        "relevance": {"type": "string", "enum": ["substantive", "peripheral", "unrelated"]},
        "relevance_evidence": {"type": "string"},
        "relevance_reason": {"type": "string"},
        "seniority_match": {
            "anyOf": [{"type": "boolean"}, {"type": "string", "enum": ["uncertain"]}]
        },
        "detected_level": {
            "type": "string",
            "enum": [
                "internship",
                "entry",
                "junior",
                "mid",
                "senior",
                "lead",
                "principal",
                "unknown",
            ],
        },
        "required_experience": {"type": "string"},
        "seniority_evidence": {"type": "string"},
        "seniority_reason": {"type": "string"},
    },
}

_LOCATION_SCHEMA_EXTRAS: dict[str, Any] = {
    "location_eligible": {
        "anyOf": [{"type": "boolean"}, {"type": "string", "enum": ["uncertain"]}]
    },
    "location_evidence": {"type": "string"},
    "location_reason": {"type": "string"},
}


def merged_response_schema(*, location_requested: bool) -> dict[str, Any]:
    """Build the strict response schema, including location only when asked.

    2.5 omits the location field entirely when the deterministic filter already resolved
    it. Enforcing that in the *schema* rather than only in the parser means the model is
    never given the opportunity to contradict a decision that was already made.
    """
    if not location_requested:
        return MERGED_RESPONSE_SCHEMA
    schema = {
        **MERGED_RESPONSE_SCHEMA,
        "properties": {**MERGED_RESPONSE_SCHEMA["properties"], **_LOCATION_SCHEMA_EXTRAS},
        "required": [
            *MERGED_RESPONSE_SCHEMA["required"],
            "location_eligible",
            "location_evidence",
            "location_reason",
        ],
    }
    return schema


@dataclass(frozen=True, slots=True)
class MergedOutcome:
    """An :class:`EvaluationOutcome` plus the relevance and location judgments.

    The seniority half is carried in ``outcome`` so existing persistence and reporting
    keep working untouched; the extra judgments ride alongside rather than replacing it.
    """

    outcome: EvaluationOutcome
    judgment: MergedJudgment | None

    @property
    def relevance(self) -> RelevanceVerdict | None:
        return self.judgment.relevance if self.judgment else None


class MergedEvaluator:
    """Run one merged call per job, with at most one retry for invalid output."""

    def __init__(
        self,
        *,
        client: Any,
        prompt: MergedPrompt,
        model_policy: ModelPolicy,
        budget: UsageBudget,
    ) -> None:
        self._client = client
        self._prompt = prompt
        self._model_policy = model_policy
        self._budget = budget
        self._last: MergedJudgment | None = None

    @property
    def prompt_version(self) -> str:
        return self._prompt.prompt_version

    @property
    def model_policy(self) -> str:
        return self._model_policy.cache_key

    @property
    def usage(self) -> UsageSnapshot:
        return self._budget.snapshot

    @property
    def last_judgment(self) -> MergedJudgment | None:
        """The full judgment from the most recent ``evaluate()`` call.

        Exposed because :class:`EvaluationOutcome` carries only the seniority decision.
        ``scan.py`` reads this immediately after evaluating to record the relevance
        verdict, so the merged call's extra judgments are not silently discarded.
        """
        return self._last

    def evaluate(
        self,
        *,
        title: str,
        description: str,
        target_description: str,
        location_original: str | None = None,
    ) -> EvaluationOutcome:
        """Evaluate one job. ``location_original`` is passed only when unresolved."""
        self._last = None
        location_requested = location_original is not None
        request = LLMRequest(
            system_prompt=self._prompt.system_prompt,
            user_prompt=self._prompt.render(
                title=title,
                description=description,
                target_description=target_description,
                location_original=location_original,
            ),
            response_schema=merged_response_schema(location_requested=location_requested),
            max_output_tokens=self._budget.limits.max_output_tokens_per_request,
        )

        errors: list[str] = []
        initial_usage = self._budget.snapshot
        for attempt in (1, 2):
            try:
                self._budget.reserve(request)
                response = self._client.complete(request, self._model_policy)
                self._budget.record(response)
                judgment = parse_merged_response(
                    response.content,
                    description=description,
                    title=title,
                    location_requested=location_requested,
                )
            except (MergedResponseError, UsageLimitExceeded) as error:
                errors.append(str(error))
                if isinstance(error, UsageLimitExceeded):
                    break
                _LOGGER.warning("merged_response_invalid attempt=%d reason=%s", attempt, error)
                continue

            self._last = judgment
            return EvaluationOutcome(
                disposition=EvaluationDisposition.COMPLETED,
                decision=SeniorityDecision(
                    seniority_match=judgment.seniority_match,
                    detected_level=judgment.detected_level,
                    required_experience=judgment.required_experience,
                    evidence=judgment.seniority_evidence,
                    reason=judgment.seniority_reason,
                ),
                attempt_count=attempt,
                errors=tuple(errors),
                usage=_usage_delta(initial_usage, self._budget.snapshot),
                prompt_version=self._prompt.prompt_version,
                model_policy=self._model_policy.cache_key,
            )

        return EvaluationOutcome(
            disposition=EvaluationDisposition.MANUAL_REVIEW,
            decision=None,
            attempt_count=self._budget.snapshot.request_count - initial_usage.request_count,
            errors=tuple(errors),
            usage=_usage_delta(initial_usage, self._budget.snapshot),
            prompt_version=self._prompt.prompt_version,
            model_policy=self._model_policy.cache_key,
        )
