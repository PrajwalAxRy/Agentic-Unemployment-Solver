"""Tests for provider-neutral seniority evaluation and usage controls."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from job_finder.matching.evaluator import (
    EvaluationDisposition,
    LLMRequest,
    LLMResponse,
    ModelPolicy,
    SeniorityEvaluator,
    UsageBudget,
    UsageLimits,
)
from job_finder.matching.prompt import load_seniority_prompt

ROOT = Path(__file__).resolve().parents[2]
DESCRIPTION = "Build ML services. Candidates need 3+ years of relevant experience."


def response_payload(
    *, match: bool | str = True, evidence: str = "3+ years of relevant experience"
) -> str:
    return json.dumps(
        {
            "seniority_match": match,
            "detected_level": "mid" if match != "uncertain" else "unknown",
            "required_experience": "3+ years" if match != "uncertain" else "unknown",
            "evidence": evidence,
            "reason": "The stated boundary permits fewer than five years.",
        }
    )


@dataclass
class StubClient:
    contents: list[str]
    requests: list[LLMRequest] = field(default_factory=list)
    policies: list[ModelPolicy] = field(default_factory=list)

    def complete(self, request: LLMRequest, policy: ModelPolicy) -> LLMResponse:
        self.requests.append(request)
        self.policies.append(policy)
        return LLMResponse(content=self.contents.pop(0), input_tokens=40, output_tokens=20)


def make_evaluator(
    client: StubClient, *, max_requests: int = 10
) -> tuple[SeniorityEvaluator, UsageBudget]:
    budget = UsageBudget(
        UsageLimits(
            max_requests=max_requests,
            max_estimated_input_tokens=10_000,
            max_output_tokens=2_000,
            max_output_tokens_per_request=200,
        )
    )
    evaluator = SeniorityEvaluator(
        client=client,
        prompt=load_seniority_prompt(ROOT / "config" / "seniority_prompt.toml"),
        model_policy=ModelPolicy(provider="test", model="stub", policy_version="1"),
        budget=budget,
    )
    return evaluator, budget


def evaluate(evaluator: SeniorityEvaluator):  # type: ignore[no-untyped-def]
    return evaluator.evaluate(
        title="Machine Learning Engineer",
        description=DESCRIPTION,
        target_description="Open to candidates with fewer than five years.",
    )


def test_valid_response_completes_and_reports_usage() -> None:
    client = StubClient([response_payload()])
    evaluator, budget = make_evaluator(client)

    outcome = evaluate(evaluator)

    assert outcome.disposition is EvaluationDisposition.COMPLETED
    assert outcome.decision is not None and outcome.decision.seniority_match is True
    assert outcome.attempt_count == 1
    assert outcome.usage.request_count == 1
    assert outcome.usage.measured_input_tokens == 40
    assert outcome.usage.measured_output_tokens == 20
    assert outcome.prompt_version == "1.0.0"
    assert outcome.model_policy == "test:stub:1"
    assert budget.snapshot.request_count == 1


def test_malformed_response_is_retried_once() -> None:
    client = StubClient(["not-json", response_payload()])
    evaluator, _ = make_evaluator(client)

    outcome = evaluate(evaluator)

    assert outcome.disposition is EvaluationDisposition.COMPLETED
    assert outcome.attempt_count == 2
    assert len(outcome.errors) == 1
    assert len(client.requests) == 2


def test_two_invalid_responses_require_manual_review() -> None:
    client = StubClient(["not-json", "still-not-json"])
    evaluator, _ = make_evaluator(client)

    outcome = evaluate(evaluator)

    assert outcome.disposition is EvaluationDisposition.MANUAL_REVIEW
    assert outcome.decision is None
    assert outcome.attempt_count == 2
    assert len(outcome.errors) == 2


def test_nonverbatim_evidence_is_retried() -> None:
    client = StubClient([response_payload(evidence="three years"), response_payload()])
    evaluator, _ = make_evaluator(client)

    outcome = evaluate(evaluator)

    assert outcome.disposition is EvaluationDisposition.COMPLETED
    assert outcome.attempt_count == 2
    assert "verbatim excerpt" in outcome.errors[0]


def test_uncertain_decision_is_a_valid_completed_outcome() -> None:
    client = StubClient([response_payload(match="uncertain", evidence="Build ML services")])
    evaluator, _ = make_evaluator(client)

    outcome = evaluate(evaluator)

    assert outcome.disposition is EvaluationDisposition.COMPLETED
    assert outcome.decision is not None
    assert outcome.decision.seniority_match == "uncertain"


def test_request_limit_prevents_retry_provider_call() -> None:
    client = StubClient(["not-json"])
    evaluator, _ = make_evaluator(client, max_requests=1)

    outcome = evaluate(evaluator)

    assert outcome.disposition is EvaluationDisposition.MANUAL_REVIEW
    assert outcome.attempt_count == 1
    assert len(client.requests) == 1
    assert any("request limit" in error for error in outcome.errors)
