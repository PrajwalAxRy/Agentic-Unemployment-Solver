"""Lab-only response contract for schema_version 2 prompts (prompts/v9.toml onwards).

Version 2 changes the answer shape, so production's parser cannot read it:
- relevance is core_ai / ai_involved / uncertain / not_ai (the first two are shown, the
  third is shown with a tag, the last is hidden);
- a one-sentence work_summary comes first;
- location, when asked, is india / open_remote / relocation / excluded / uncertain.
Seniority is unchanged. Evidence is validated with production's own checker, so a quote
that production would reject is rejected here too.

Nothing in src/ imports this. If the experiment wins, the contract moves into production
with tests; until then it stays here so a lab prompt cannot reach a real scan.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from job_finder.matching.evaluator import (
    EvaluationDisposition,
    LLMRequest,
    UsageBudget,
    _usage_delta,
)
from job_finder.matching.merged_prompt import (
    MergedPrompt,
    MergedResponseError,
    _detected_level,
    _evidence,
    _required_text,
    _seniority_match,
)
from job_finder.matching.seniority import DetectedLevel

RELEVANCE = ("core_ai", "ai_involved", "uncertain", "not_ai")
SHOWN = {"core_ai", "ai_involved", "uncertain"}
LOCATION = ("india", "open_remote", "relocation", "excluded", "uncertain")

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    # The model writes fields in this order: the summary of the work comes before the
    # verdict it should inform.
    "required": [
        "work_summary",
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
        "work_summary": {"type": "string"},
        "relevance": {"type": "string", "enum": list(RELEVANCE)},
        "relevance_evidence": {"type": "string"},
        "relevance_reason": {"type": "string"},
        "seniority_match": {
            "anyOf": [{"type": "boolean"}, {"type": "string", "enum": ["uncertain"]}]
        },
        "detected_level": {"type": "string", "enum": [level.value for level in DetectedLevel]},
        "required_experience": {"type": "string"},
        "seniority_evidence": {"type": "string"},
        "seniority_reason": {"type": "string"},
    },
}
_LOCATION_FIELDS: dict[str, Any] = {
    "location_fit": {"type": "string", "enum": list(LOCATION)},
    "location_evidence": {"type": "string"},
    "location_reason": {"type": "string"},
}


def schema(*, location_requested: bool) -> dict[str, Any]:
    if not location_requested:
        return SCHEMA
    return {
        **SCHEMA,
        "properties": {**SCHEMA["properties"], **_LOCATION_FIELDS},
        "required": [*SCHEMA["required"], *_LOCATION_FIELDS],
    }


def prompt_schema_version(path: Path) -> int:
    with path.open("rb") as stream:
        return int(tomllib.load(stream).get("schema_version", 0))


def load_prompt(path: Path) -> MergedPrompt:
    """Load a schema_version 2 prompt; same text fields as version 1."""
    with path.open("rb") as stream:
        raw = tomllib.load(stream)
    if raw.get("schema_version") != 2:
        raise ValueError(f"{path} is not a schema_version 2 prompt")
    prompt = MergedPrompt(
        schema_version=2,
        prompt_version=raw["prompt_version"],
        system_prompt=raw["system_prompt"],
        user_prompt_template=raw["user_prompt_template"],
        location_section_template=raw["location_section_template"],
    )
    for placeholder in ("{title}", "{description}", "{target_description}", "{location_section}"):
        if placeholder not in prompt.user_prompt_template:
            raise ValueError(f"user_prompt_template must contain {placeholder}")
    return prompt


def parse(
    content: str,
    *,
    description: str,
    title: str,
    location_original: str | None,
) -> dict[str, Any]:
    """Validate one reply and return it as a plain dict (the lab stores JSON)."""
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as error:
        raise MergedResponseError("response was not valid JSON") from error
    if not isinstance(raw, Mapping):
        raise MergedResponseError("response must be a JSON object")
    sources = (description, title) if title else (description,)
    relevance = raw.get("relevance")
    if relevance not in RELEVANCE:
        raise MergedResponseError(f"relevance must be one of: {', '.join(RELEVANCE)}")
    judgment: dict[str, Any] = {
        "work_summary": _required_text(raw.get("work_summary"), "work_summary"),
        "relevance": relevance,
        "relevance_evidence": _evidence(raw, "relevance_evidence", sources),
        "relevance_reason": _required_text(raw.get("relevance_reason"), "relevance_reason"),
        "seniority_match": _seniority_match(raw.get("seniority_match")),
        "detected_level": _detected_level(raw.get("detected_level")).value,
        "required_experience": _required_text(
            raw.get("required_experience"), "required_experience"
        ),
        "seniority_evidence": _evidence(raw, "seniority_evidence", sources),
        "seniority_reason": _required_text(raw.get("seniority_reason"), "seniority_reason"),
    }
    if location_original is not None:
        if raw.get("location_fit") not in LOCATION:
            raise MergedResponseError(f"location_fit must be one of: {', '.join(LOCATION)}")
        judgment["location_fit"] = raw["location_fit"]
        judgment["location_evidence"] = _evidence(
            raw, "location_evidence", (*sources, location_original)
        )
        judgment["location_reason"] = _required_text(raw.get("location_reason"), "location_reason")
    elif "location_fit" in raw:
        raise MergedResponseError("location_fit given but location was not requested")
    return judgment


@dataclass
class Outcome:
    """Shaped like production's EvaluationOutcome where the lab reads it."""

    disposition: EvaluationDisposition
    judgment: dict[str, Any] | None
    errors: tuple[str, ...] = ()
    usage: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


class Evaluator:
    """One call per job, at most one retry for an invalid reply (as in production)."""

    def __init__(
        self, *, client: Any, prompt: MergedPrompt, model_policy: Any, budget: UsageBudget
    ) -> None:
        self._client, self._prompt = client, prompt
        self._policy, self._budget = model_policy, budget

    def evaluate(
        self,
        *,
        title: str,
        description: str,
        target_description: str,
        location_original: str | None = None,
    ) -> Outcome:
        request = LLMRequest(
            system_prompt=self._prompt.system_prompt,
            user_prompt=self._prompt.render(
                title=title,
                description=description,
                target_description=target_description,
                location_original=location_original,
            ),
            response_schema=schema(location_requested=location_original is not None),
            max_output_tokens=self._budget.limits.max_output_tokens_per_request,
        )
        before, errors = self._budget.snapshot, []
        for _attempt in (1, 2):
            self._budget.reserve(request)
            response = self._client.complete(request, self._policy)
            self._budget.record(response)
            try:
                judgment = parse(
                    response.content,
                    description=description,
                    title=title,
                    location_original=location_original,
                )
            except MergedResponseError as error:
                errors.append(str(error))
                continue
            return Outcome(
                EvaluationDisposition.COMPLETED,
                judgment,
                tuple(errors),
                _usage_delta(before, self._budget.snapshot),
            )
        return Outcome(
            EvaluationDisposition.MANUAL_REVIEW,
            None,
            tuple(errors),
            _usage_delta(before, self._budget.snapshot),
        )
