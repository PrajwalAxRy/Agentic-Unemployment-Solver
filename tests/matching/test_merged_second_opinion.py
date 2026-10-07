"""Second opinion on the relevance gate (JOB_FINDER_LLM_SECOND_OPINION).

Measured on the 2026-10-02 batch: the same request flips across "not_ai" on ~2% of
ordinary jobs and ~8% of borderline ones. These tests pin the decision rule: ask twice,
ask a third time only on a gate disagreement, majority wins, and with no majority the
passing answer wins because a missed job costs more than an extra one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from job_finder.matching.evaluator import (
    EvaluationDisposition,
    LLMRequest,
    LLMResponse,
    ModelPolicy,
    UsageBudget,
    UsageLimits,
)
from job_finder.matching.merged_evaluator import MergedEvaluator
from job_finder.matching.merged_prompt import RelevanceTier, load_merged_prompt

ROOT = Path(__file__).resolve().parents[2]
DESCRIPTION = (
    "Design and build large-scale machine learning systems for Ads ranking. You will "
    "train and evaluate deep models. Requires 3+ years of relevant experience."
)


def reply(relevance: str) -> str:
    return json.dumps(
        {
            "work_summary": "Builds ranking models for Ads.",
            "relevance": relevance,
            "relevance_evidence": "train and evaluate deep models",
            "relevance_reason": "Judged from the duties.",
            "seniority_match": True,
            "detected_level": "mid",
            "required_experience": "3+ years",
            "seniority_evidence": "Requires 3+ years of relevant experience",
            "seniority_reason": "The stated minimum is below five years.",
        }
    )


@dataclass
class QueueClient:
    contents: list[str]
    requests: list[LLMRequest] = field(default_factory=list)

    def complete(self, request: LLMRequest, policy: ModelPolicy) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(self.contents.pop(0), input_tokens=10, output_tokens=5)


def evaluate(contents: list[str], *, second_opinion: bool = True, max_requests: int = 20):
    client = QueueClient(list(contents))
    evaluator = MergedEvaluator(
        client=client,
        prompt=load_merged_prompt(ROOT / "config" / "merged_prompt.toml"),
        model_policy=ModelPolicy("test", "stub", "1"),
        budget=UsageBudget(UsageLimits(max_requests, 100_000, 10_000, 200)),
        second_opinion=second_opinion,
    )
    outcome = evaluator.evaluate(
        title="ML Engineer", description=DESCRIPTION, target_description="fewer than 5 years"
    )
    return outcome, client


@pytest.mark.parametrize(
    ("replies", "calls", "verdict"),
    [
        # Agreement on the gate: two calls, the first answer stands.
        (["core_ai", "ai_involved"], 2, "core_ai"),
        (["not_ai", "not_ai"], 2, "not_ai"),
        # Disagreement: a third call decides.
        (["not_ai", "core_ai", "ai_involved"], 3, "core_ai"),
        (["core_ai", "not_ai", "not_ai"], 3, "not_ai"),
        (["not_ai", "ai_involved", "not_ai"], 3, "not_ai"),
    ],
)
def test_majority_on_the_relevance_gate(replies, calls, verdict) -> None:
    outcome, client = evaluate([reply(r) for r in replies])

    assert outcome.disposition is EvaluationDisposition.COMPLETED
    assert len(client.requests) == calls
    assert outcome.attempt_count == calls
    assert outcome.judgment is not None
    assert outcome.judgment.relevance is RelevanceTier(verdict)


def test_no_majority_keeps_the_passing_answer() -> None:
    # The third reply is invalid twice, so only one vote on each side survives.
    outcome, client = evaluate([reply("not_ai"), reply("ai_involved"), "not json", "{}"])

    assert len(client.requests) == 4
    assert outcome.judgment is not None
    assert outcome.judgment.relevance is RelevanceTier.AI_INVOLVED


def test_invalid_second_opinion_leaves_the_first_answer() -> None:
    outcome, client = evaluate([reply("not_ai"), "not json", "{}"])

    assert len(client.requests) == 3
    assert outcome.disposition is EvaluationDisposition.COMPLETED
    assert outcome.judgment is not None
    assert outcome.judgment.relevance is RelevanceTier.NOT_AI


def test_budget_exhaustion_after_a_valid_answer_keeps_that_answer() -> None:
    outcome, client = evaluate([reply("ai_involved")], max_requests=1)

    assert len(client.requests) == 1
    assert outcome.disposition is EvaluationDisposition.COMPLETED
    assert outcome.judgment is not None
    assert outcome.judgment.relevance is RelevanceTier.AI_INVOLVED


def test_disabled_by_default_makes_one_call() -> None:
    outcome, client = evaluate([reply("not_ai")], second_opinion=False)

    assert len(client.requests) == 1
    assert outcome.attempt_count == 1
    assert outcome.judgment is not None


def test_enabling_changes_the_configuration_fingerprint_only_when_on() -> None:
    def fingerprint(enabled: bool) -> str:
        return MergedEvaluator(
            client=QueueClient([]),
            prompt=load_merged_prompt(ROOT / "config" / "merged_prompt.toml"),
            model_policy=ModelPolicy("test", "stub", "1"),
            budget=UsageBudget(UsageLimits(20, 100_000, 10_000, 200)),
            second_opinion=enabled,
        ).configuration_fingerprint

    assert fingerprint(True) != fingerprint(False)
