"""Human-labelled examples for the description-based AI/ML relevance gate.

``to_change.md`` 2.3 replaces the regex relevance filter with a mandatory LLM judgment.
The regex gate it replaces ran **ten times in the entire 2026-09-29 scan**
(``conditional_pass_count: 5``, ``conditional_rejection_count: 5``) -- it was never the
real AI filter; title substring matching was. Replacing it therefore moves the decision
about what counts as an AI/ML job onto a component with no measurement at all, which is
why this eval set exists before the gate ships.

The set is grounded in real failures rather than invented ones. Most cases carry
``source: scan-2026-09-29`` and use titles that genuinely appeared in that scan, including
every negative class 2.3 names:

* AI in the org blurb, absent from duties and quals (RBS Tech)
* AI as a tool the engineer uses ("generative AI to improve team productivity")
* AI in the team name only (DevOps Engineer II, Ads AI Core Infra)
* AI-assisted development rather than AI products (Native-AI SDLC)

Verdicts are three-way, matching 2.6: ``substantive`` / ``peripheral`` / ``unrelated``.
Only a confident ``unrelated`` drops a row; ``peripheral`` still displays, tiered lower.
Forcing a binary here would hide uncertainty rather than remove it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from job_finder.core.validation import required_string


class RelevanceVerdict(StrEnum):
    """Three-way relevance judgment (``to_change.md`` 2.3, 2.6) of merged prompt 1.x.

    Legacy: production answers with :class:`~job_finder.matching.merged_prompt.RelevanceTier`
    since prompt 2.0.0. Kept only for the inert evaluation set it labels.
    """

    SUBSTANTIVE = "substantive"
    """The engineer builds, trains, evaluates or operates AI/ML systems."""

    PERIPHERAL = "peripheral"
    """Genuinely adjacent to AI/ML but not building it. Displays, tiered lower."""

    UNRELATED = "unrelated"
    """AI is absent, or present only as setting, tooling, or team name. The only
    verdict that drops a row."""


@dataclass(frozen=True, slots=True)
class RelevanceExample:
    """One human-labelled job description."""

    example_id: str
    title: str
    description: str
    expected_verdict: RelevanceVerdict
    human_rationale: str
    important_evidence: str
    source: str | None = None


@dataclass(frozen=True, slots=True)
class RelevanceEvaluationSet:
    """Versioned collection of human-labelled relevance cases."""

    schema_version: int
    set_version: str
    profile_id: str
    examples: tuple[RelevanceExample, ...]

    def by_verdict(self, verdict: RelevanceVerdict) -> tuple[RelevanceExample, ...]:
        return tuple(item for item in self.examples if item.expected_verdict is verdict)


def load_relevance_evaluation_set(path: Path) -> RelevanceEvaluationSet:
    """Load and validate the reviewed relevance evaluation set."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("relevance evaluation set must be valid JSON") from error
    if not isinstance(raw, Mapping):
        raise ValueError("relevance evaluation set root must be an object")

    schema_version = raw.get("schema_version")
    if schema_version != 1:
        raise ValueError(f"unsupported relevance evaluation schema_version: {schema_version}")

    examples_raw = raw.get("examples")
    if not isinstance(examples_raw, list) or not examples_raw:
        raise ValueError("relevance evaluation set.examples must be a non-empty array")

    examples: list[RelevanceExample] = []
    seen_ids: set[str] = set()
    for index, value in enumerate(examples_raw):
        path_name = f"examples[{index}]"
        if not isinstance(value, Mapping):
            raise ValueError(f"{path_name} must be an object")
        example_id = required_string(value, "id", path_name)
        if example_id in seen_ids:
            raise ValueError(f"duplicate relevance evaluation id: {example_id}")
        seen_ids.add(example_id)

        description = required_string(value, "description", path_name)
        important_evidence = required_string(value, "important_evidence", path_name)
        # Same discipline the seniority set enforces: the cited evidence must actually
        # appear in the description, so a label cannot drift away from its justification.
        if important_evidence.casefold() not in description.casefold():
            raise ValueError(
                f"{path_name}.important_evidence must occur verbatim in the description"
            )

        source = value.get("source")
        examples.append(
            RelevanceExample(
                example_id=example_id,
                title=required_string(value, "title", path_name),
                description=description,
                expected_verdict=_expected_verdict(value.get("expected_verdict"), path_name),
                human_rationale=required_string(value, "human_rationale", path_name),
                important_evidence=important_evidence,
                source=source if isinstance(source, str) and source.strip() else None,
            )
        )

    return RelevanceEvaluationSet(
        schema_version=schema_version,
        set_version=required_string(raw, "set_version", "relevance evaluation set"),
        profile_id=required_string(raw, "profile_id", "relevance evaluation set"),
        examples=tuple(examples),
    )


def _expected_verdict(value: object, path: str) -> RelevanceVerdict:
    if not isinstance(value, str):
        raise ValueError(f"{path}.expected_verdict must be a string")
    try:
        return RelevanceVerdict(value)
    except ValueError as error:
        supported = ", ".join(item.value for item in RelevanceVerdict)
        raise ValueError(f"{path}.expected_verdict must be one of: {supported}") from error
