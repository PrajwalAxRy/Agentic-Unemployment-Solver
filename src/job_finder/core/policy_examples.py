"""Labelled product-policy examples approved at checkpoint H1."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from job_finder.core.validation import required_string


class RoleExampleDecision(StrEnum):
    """Expected pre-seniority role decision."""

    EXPLICIT_PASS = "explicit_pass"
    CONDITIONAL_DESCRIPTION = "conditional_description"
    REJECT = "reject"


class LocationExampleDecision(StrEnum):
    """Expected deterministic India-location decision."""

    PASS = "pass"
    REVIEW = "review"
    REJECT = "reject"


class SeniorityExampleDecision(StrEnum):
    """Expected later LLM seniority decision."""

    INCLUDE = "include"
    EXCLUDE = "exclude"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class RoleExample:
    example_id: str
    title: str
    expected: RoleExampleDecision
    reason: str


@dataclass(frozen=True, slots=True)
class LocationExample:
    example_id: str
    source_location: str | None
    expected: LocationExampleDecision
    reason: str


@dataclass(frozen=True, slots=True)
class SeniorityExample:
    example_id: str
    evidence: str
    expected: SeniorityExampleDecision
    rationale: str


@dataclass(frozen=True, slots=True)
class PolicyExamples:
    schema_version: int
    profile_id: str
    profile_version: str
    role: tuple[RoleExample, ...]
    location: tuple[LocationExample, ...]
    seniority: tuple[SeniorityExample, ...]


def load_policy_examples(path: Path) -> PolicyExamples:
    """Load and validate the labelled H1 examples."""
    with path.open("rb") as stream:
        raw: dict[str, object] = tomllib.load(stream)
    schema_version = _required_int(raw, "schema_version", "examples")
    if schema_version != 1:
        raise ValueError(
            f"unsupported policy examples schema_version: {schema_version}; supported=1"
        )

    role = tuple(
        RoleExample(
            example_id=required_string(item, "id", path_name),
            title=required_string(item, "title", path_name),
            expected=_enum_value(
                RoleExampleDecision,
                required_string(item, "expected", path_name),
                f"{path_name}.expected",
            ),
            reason=required_string(item, "reason", path_name),
        )
        for path_name, item in _example_mappings(raw, "role")
    )
    location = tuple(
        LocationExample(
            example_id=required_string(item, "id", path_name),
            source_location=_nullable_string(
                item.get("source_location"), f"{path_name}.source_location"
            ),
            expected=_enum_value(
                LocationExampleDecision,
                required_string(item, "expected", path_name),
                f"{path_name}.expected",
            ),
            reason=required_string(item, "reason", path_name),
        )
        for path_name, item in _example_mappings(raw, "location")
    )
    seniority = tuple(
        SeniorityExample(
            example_id=required_string(item, "id", path_name),
            evidence=required_string(item, "evidence", path_name),
            expected=_enum_value(
                SeniorityExampleDecision,
                required_string(item, "expected", path_name),
                f"{path_name}.expected",
            ),
            rationale=required_string(item, "rationale", path_name),
        )
        for path_name, item in _example_mappings(raw, "seniority")
    )
    if len(seniority) < 10:
        raise ValueError("policy examples require at least ten seniority examples")

    all_ids = [item.example_id for item in role]
    all_ids.extend(item.example_id for item in location)
    all_ids.extend(item.example_id for item in seniority)
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("policy example IDs must be unique")

    return PolicyExamples(
        schema_version=schema_version,
        profile_id=required_string(raw, "profile_id", "examples"),
        profile_version=required_string(raw, "profile_version", "examples"),
        role=role,
        location=location,
        seniority=seniority,
    )


def _example_mappings(
    raw: Mapping[str, object],
    key: str,
) -> tuple[tuple[str, Mapping[str, object]], ...]:
    value = raw.get(key)
    if not isinstance(value, list) or not value:
        raise ValueError(f"examples.{key} must be a non-empty array")
    items: list[tuple[str, Mapping[str, object]]] = []
    for index, item in enumerate(value):
        path = f"examples.{key}[{index}]"
        if not isinstance(item, Mapping):
            raise ValueError(f"{path} must be a table")
        items.append((path, item))
    return tuple(items)


def _nullable_string(value: object, path: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be null or a non-empty string")
    return value.strip()


def _required_int(raw: Mapping[str, object], key: str, path: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{path}.{key} must be an integer")
    return value


def _enum_value[EnumType: StrEnum](
    enum_type: type[EnumType],
    value: str,
    path: str,
) -> EnumType:
    try:
        return enum_type(value)
    except ValueError as error:
        supported = ", ".join(item.value for item in enum_type)
        raise ValueError(f"{path} must be one of: {supported}") from error
