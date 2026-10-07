"""One real merged call with production settings: confirms prompt 2.0.0 and effort end to end.

  uv run --locked python experiments/llm_compare/lab/smoke_production.py   (repo root)

Loads .env exactly as a scan does, evaluates one built-in job through the production
MergedEvaluator, and prints the request settings that reached the gateway and the parsed
judgment. No secret is printed; nothing is written to state/. Cost: one call (~$0.0004).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from job_finder.matching.evaluator import UsageBudget
from job_finder.matching.merged_evaluator import MergedEvaluator
from job_finder.matching.merged_prompt import load_merged_prompt
from job_finder.matching.openai_client import (
    AmdGatewayClient,
    _gateway_client,
    load_gateway_settings,
)

TITLE = "Machine Learning Engineer, Search Ranking"
DESCRIPTION = (
    "You will design, train and deploy learning-to-rank models for product search, run "
    "offline evaluation and online A/B tests, and own the model-serving pipeline. "
    "Requirements: 3+ years of experience building production ML systems in Python; "
    "experience with PyTorch or TensorFlow. Location: Bengaluru, India."
)
TARGET = "A candidate with about three years of experience (fewer than five)."


class _Recorder:
    """Wraps the OpenAI client and keeps the non-secret create() arguments."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.chat = self
        self.completions = self
        self.sent: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        self.sent = {k: v for k, v in kwargs.items() if k not in {"messages", "response_format"}}
        self.sent["schema_name"] = kwargs["response_format"]["json_schema"]["name"]
        return self._inner.chat.completions.create(**kwargs)


def main() -> int:
    settings = load_gateway_settings()
    prompt = load_merged_prompt(Path("config/merged_prompt.toml"))
    recorder = _Recorder(_gateway_client(settings))
    evaluator = MergedEvaluator(
        client=AmdGatewayClient(settings, client=recorder),
        prompt=prompt,
        model_policy=settings.model_policy,
        budget=UsageBudget(settings.usage_limits),
    )
    outcome = evaluator.evaluate(title=TITLE, description=DESCRIPTION, target_description=TARGET)

    print(f"prompt {prompt.prompt_version} (schema {prompt.schema_version})")
    print(f"model policy {settings.model_policy.cache_key}")
    print(f"sent to gateway {recorder.sent}")
    print(f"disposition {outcome.disposition.value}, errors {list(outcome.errors)}")
    judgment = outcome.judgment
    if judgment is None:
        print("no valid judgment")
        return 1
    print(f"work_summary: {judgment.work_summary}")
    print(f"relevance: {judgment.relevance.value} -- {judgment.relevance_reason}")
    print(f"seniority_match: {judgment.seniority_match} ({judgment.required_experience})")
    if settings.reasoning_effort is None:
        print("NOTE: JOB_FINDER_LLM_REASONING_EFFORT is not set; production chose 'high'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
