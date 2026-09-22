"""Versioned reviewed examples for seniority evaluator quality measurement."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from job_finder.matching.seniority import DetectedLevel, SeniorityMatch


@dataclass(frozen=True, slots=True)
class SeniorityEvaluationExample:
    """One human-labelled synthetic job description."""

    example_id: str
    title: str
    description: str
    expected_match: SeniorityMatch
    expected_level: DetectedLevel
    human_rationale: str
    important_evidence: str


@dataclass(frozen=True, slots=True)
class SeniorityEvaluationSet:
    """Versioned collection of human-labelled seniority cases."""

    schema_version: int
    set_version: str
    profile_id: str
    examples: tuple[SeniorityEvaluationExample, ...]


def load_seniority_evaluation_set(path: Path) -> SeniorityEvaluationSet:
    """Load and validate the reviewed JSON evaluation set."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("seniority evaluation set must be valid JSON") from error
    if not isinstance(raw, Mapping):
        raise ValueError("seniority evaluation set root must be an object")
    schema_version = _required_int(raw, "schema_version", "evaluation set")
    if schema_version != 1:
        raise ValueError(f"unsupported seniority evaluation schema_version: {schema_version}")
    set_version = _required_string(raw, "set_version", "evaluation set")
    profile_id = _required_string(raw, "profile_id", "evaluation set")
    examples_raw = raw.get("examples")
    if not isinstance(examples_raw, list) or not examples_raw:
        raise ValueError("evaluation set.examples must be a non-empty array")

    examples: list[SeniorityEvaluationExample] = []
    seen_ids: set[str] = set()
    for index, value in enumerate(examples_raw):
        path_name = f"examples[{index}]"
        if not isinstance(value, Mapping):
            raise ValueError(f"{path_name} must be an object")
        example_id = _required_string(value, "id", path_name)
        if example_id in seen_ids:
            raise ValueError(f"duplicate seniority evaluation id: {example_id}")
        seen_ids.add(example_id)
        description = _required_string(value, "description", path_name)
        important_evidence = _required_string(value, "important_evidence", path_name)
        if important_evidence.casefold() not in description.casefold():
            raise ValueError(f"{path_name}.important_evidence must occur in the description")
        examples.append(
            SeniorityEvaluationExample(
                example_id=example_id,
                title=_required_string(value, "title", path_name),
                description=description,
                expected_match=_expected_match(value.get("expected_match"), path_name),
                expected_level=_expected_level(value.get("expected_level"), path_name),
                human_rationale=_required_string(value, "human_rationale", path_name),
                important_evidence=important_evidence,
            )
        )
    return SeniorityEvaluationSet(
        schema_version=schema_version,
        set_version=set_version,
        profile_id=profile_id,
        examples=tuple(examples),
    )


def _expected_match(value: object, path: str) -> SeniorityMatch:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value == "uncertain":
        return "uncertain"
    raise ValueError(f"{path}.expected_match must be true, false, or 'uncertain'")


def _expected_level(value: object, path: str) -> DetectedLevel:
    if not isinstance(value, str):
        raise ValueError(f"{path}.expected_level must be a string")
    try:
        return DetectedLevel(value)
    except ValueError as error:
        raise ValueError(f"{path}.expected_level is not a supported level") from error


def _required_string(raw: Mapping[str, object], key: str, path: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}.{key} must be a non-empty string")
    return value.strip()


def _required_int(raw: Mapping[str, object], key: str, path: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{path}.{key} must be an integer")
    return value
