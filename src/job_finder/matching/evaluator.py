"""Provider-neutral, budgeted seniority evaluation with strict retry behavior."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from job_finder.matching.merged_prompt import MergedJudgment
from job_finder.matching.prompt import SeniorityPrompt
from job_finder.matching.seniority import (
    RESPONSE_JSON_SCHEMA,
    SeniorityDecision,
    SeniorityResponseError,
    parse_seniority_response,
)

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class ModelPolicy:
    """Provider/model identity that participates in evaluation caching."""

    provider: str
    model: str
    policy_version: str
    reasoning_effort: str | None = None
    """Gateway reasoning effort, or None to leave the provider default. Effort changes the
    answers, so it is part of the cache identity; unset keeps the historical key."""

    @property
    def cache_key(self) -> str:
        key = f"{self.provider}:{self.model}:{self.policy_version}"
        return key if self.reasoning_effort is None else f"{key}:effort={self.reasoning_effort}"


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """Minimal request passed to a provider adapter."""

    system_prompt: str
    user_prompt: str
    response_schema: Mapping[str, object]
    max_output_tokens: int


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Provider response text and measured usage."""

    content: str
    input_tokens: int
    output_tokens: int
    usage_known: bool = True
    # Subsets of input_tokens/output_tokens, billed differently or worth watching. None
    # means the provider did not report the breakdown, which is not the same as zero.
    # Defaulted so replies journaled before these existed still replay.
    cached_input_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None


class SeniorityLLMClient(Protocol):
    """Provider-neutral completion interface."""

    def complete(self, request: LLMRequest, policy: ModelPolicy) -> LLMResponse: ...


class LLMProviderError(RuntimeError):
    """Sanitized transport/response failure, optionally carrying already billed usage."""

    def __init__(self, message: str, *, response: LLMResponse | None = None) -> None:
        super().__init__(message)
        self.response = response


@dataclass(frozen=True, slots=True)
class UsageLimits:
    """Hard per-run request and token ceilings."""

    max_requests: int
    max_estimated_input_tokens: int
    max_output_tokens: int
    max_output_tokens_per_request: int

    def __post_init__(self) -> None:
        if (
            min(
                self.max_requests,
                self.max_estimated_input_tokens,
                self.max_output_tokens,
                self.max_output_tokens_per_request,
            )
            <= 0
        ):
            raise ValueError("all usage limits must be positive")


@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    """Usage reserved and measured during one process run."""

    request_count: int
    estimated_input_tokens: int
    measured_input_tokens: int
    measured_output_tokens: int


class UsageLimitExceeded(RuntimeError):
    """A request would exceed the configured run budget."""


class UsageBudget:
    """Mutable per-run budget shared by evaluator calls."""

    def __init__(self, limits: UsageLimits) -> None:
        self.limits = limits
        self._request_count = 0
        self._estimated_input_tokens = 0
        self._measured_input_tokens = 0
        self._measured_output_tokens = 0
        self._unknown_output_bound = 0

    @property
    def snapshot(self) -> UsageSnapshot:
        return UsageSnapshot(
            request_count=self._request_count,
            estimated_input_tokens=self._estimated_input_tokens,
            measured_input_tokens=self._measured_input_tokens,
            measured_output_tokens=self._measured_output_tokens,
        )

    def reserve(self, request: LLMRequest) -> None:
        """Reserve one call using a conservative character-based input estimate."""
        estimated = math.ceil((len(request.system_prompt) + len(request.user_prompt)) / 4)
        if self._request_count + 1 > self.limits.max_requests:
            raise UsageLimitExceeded("LLM request limit reached")
        if self._estimated_input_tokens + estimated > self.limits.max_estimated_input_tokens:
            raise UsageLimitExceeded("estimated LLM input-token limit reached")
        if request.max_output_tokens > self.limits.max_output_tokens_per_request:
            raise UsageLimitExceeded("per-request LLM output-token limit exceeded")
        if (
            self._measured_output_tokens + self._unknown_output_bound + request.max_output_tokens
            > self.limits.max_output_tokens
        ):
            raise UsageLimitExceeded("LLM output-token limit reached")
        self._request_count += 1
        self._estimated_input_tokens += estimated

    def record(self, response: LLMResponse) -> None:
        """Record non-negative provider-reported usage after a reserved request."""
        if response.input_tokens < 0 or response.output_tokens < 0:
            raise ValueError("provider token usage cannot be negative")
        if not response.usage_known:
            self._unknown_output_bound += self.limits.max_output_tokens_per_request
            return
        self._measured_input_tokens += response.input_tokens
        self._measured_output_tokens += response.output_tokens
        if self._measured_output_tokens > self.limits.max_output_tokens:
            raise UsageLimitExceeded("measured LLM output-token limit exceeded")


class EvaluationDisposition(StrEnum):
    """Whether a job received a validated decision or needs manual review."""

    COMPLETED = "completed"
    MANUAL_REVIEW = "manual_review"
    BUDGET_EXHAUSTED = "budget_exhausted"
    """The run budget ran out before this job was judged.

    Distinct from MANUAL_REVIEW because it says nothing about the job: the model never
    saw it. Conflating the two cost 3,026 records in the 2026-09-30 scan, which were
    written as invalid_seniority_output and so became permanently unretryable.
    """


@dataclass(frozen=True, slots=True)
class EvaluationOutcome:
    """One evaluator result including retry evidence and usage delta."""

    disposition: EvaluationDisposition
    decision: SeniorityDecision | None
    attempt_count: int
    errors: tuple[str, ...]
    usage: UsageSnapshot
    prompt_version: str
    model_policy: str
    judgment: MergedJudgment | None = None
    """The merged call's full three-part judgment, when one was made.

    ``decision`` carries only the seniority half, so without this the relevance and
    location evidence the model was paid to produce is discarded at the point it is
    converted to a :class:`SeniorityDecision`. Optional because ``SeniorityEvaluator``
    makes no such judgment -- ``--seniority-only`` must stay a drop-in fallback.
    """


class SeniorityEvaluator:
    """Render, call, validate, retry once, and preserve uncertain/manual outcomes."""

    def __init__(
        self,
        *,
        client: SeniorityLLMClient,
        prompt: SeniorityPrompt,
        model_policy: ModelPolicy,
        budget: UsageBudget,
    ) -> None:
        self._client = client
        self._prompt = prompt
        self._model_policy = model_policy
        self._budget = budget

    @property
    def prompt_version(self) -> str:
        """Return the version used for cache invalidation and reporting."""
        return self._prompt.prompt_version

    @property
    def model_policy(self) -> str:
        """Return the stable provider/model policy cache key."""
        return self._model_policy.cache_key

    @property
    def usage(self) -> UsageSnapshot:
        """Return aggregate sanitized usage for the current process run."""
        return self._budget.snapshot

    @property
    def client(self) -> SeniorityLLMClient:
        return self._client

    @client.setter
    def client(self, value: SeniorityLLMClient) -> None:
        self._client = value

    @property
    def configuration_fingerprint(self) -> str:
        from dataclasses import asdict

        from job_finder.matching.journal import fingerprint

        return fingerprint(
            {
                "prompt": asdict(self._prompt),
                "model": self.model_policy,
                "max_output_tokens": self._budget.limits.max_output_tokens_per_request,
            }
        )

    def build_request(
        self,
        *,
        title: str,
        description: str,
        target_description: str,
        location_original: str | None = None,
    ) -> LLMRequest:
        return LLMRequest(
            system_prompt=self._prompt.system_prompt,
            user_prompt=self._prompt.render(
                title=title,
                description=description,
                target_description=target_description,
            ),
            response_schema=RESPONSE_JSON_SCHEMA,
            max_output_tokens=self._budget.limits.max_output_tokens_per_request,
        )

    def evaluate(
        self,
        *,
        title: str,
        description: str,
        target_description: str,
        location_original: str | None = None,
    ) -> EvaluationOutcome:
        """Evaluate one description with at most one retry for invalid output.

        ``location_original`` is accepted and ignored. This evaluator judges seniority
        only; the parameter exists so it remains interchangeable with MergedEvaluator,
        which is what keeps --seniority-only a one-flag fallback (2.5).
        """
        request = self.build_request(
            title=title,
            description=description,
            target_description=target_description,
            location_original=location_original,
        )
        errors: list[str] = []
        initial_usage = self._budget.snapshot
        for attempt in (1, 2):
            try:
                replaying = bool(getattr(self._client, "has_replay", False))
                if not replaying:
                    self._budget.reserve(request)
                response = self._client.complete(request, self._model_policy)
                if not replaying:
                    self._budget.record(response)
                decision = parse_seniority_response(response.content)
                _require_description_evidence(decision, description)
            except UsageLimitExceeded as error:
                # Same distinction as MergedEvaluator: the budget ran out, so this job
                # was never judged. Falling through to MANUAL_REVIEW would claim it was.
                return EvaluationOutcome(
                    disposition=EvaluationDisposition.BUDGET_EXHAUSTED,
                    decision=None,
                    attempt_count=attempt - 1,
                    # Keep any earlier attempt's errors: a malformed response followed by
                    # budget exhaustion should not lose the malformed-response context.
                    errors=(*errors, str(error)),
                    usage=_usage_delta(initial_usage, self._budget.snapshot),
                    prompt_version=self._prompt.prompt_version,
                    model_policy=self._model_policy.cache_key,
                )
            except SeniorityResponseError as error:
                errors.append(str(error))
                continue
            return EvaluationOutcome(
                disposition=EvaluationDisposition.COMPLETED,
                decision=decision,
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


def _require_description_evidence(decision: SeniorityDecision, description: str) -> None:
    normalized_description = _WHITESPACE.sub(" ", description).casefold()
    normalized_evidence = _WHITESPACE.sub(" ", decision.evidence).casefold()
    if normalized_evidence not in normalized_description:
        raise SeniorityResponseError("evidence must be a verbatim excerpt from the description")


def _usage_delta(before: UsageSnapshot, after: UsageSnapshot) -> UsageSnapshot:
    return UsageSnapshot(
        request_count=after.request_count - before.request_count,
        estimated_input_tokens=after.estimated_input_tokens - before.estimated_input_tokens,
        measured_input_tokens=after.measured_input_tokens - before.measured_input_tokens,
        measured_output_tokens=after.measured_output_tokens - before.measured_output_tokens,
    )
