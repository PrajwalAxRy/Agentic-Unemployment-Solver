"""Strict seniority taxonomy and structured LLM response contract."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Literal

SeniorityMatch = bool | Literal["uncertain"]


class DetectedLevel(StrEnum):
    """Normalized seniority levels allowed in model output."""

    INTERNSHIP = "internship"
    ENTRY = "entry"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    STAFF = "staff"
    PRINCIPAL = "principal"
    MANAGER = "manager"
    DIRECTOR = "director"
    EXECUTIVE = "executive"
    UNKNOWN = "unknown"


class SeniorityResponseError(ValueError):
    """A model response does not satisfy the strict seniority contract."""


@dataclass(frozen=True, slots=True)
class SeniorityDecision:
    """Validated, explainable decision returned by the seniority evaluator."""

    seniority_match: SeniorityMatch
    detected_level: DetectedLevel
    required_experience: str
    evidence: str
    reason: str

    def as_json(self) -> dict[str, object]:
        """Return a JSON-compatible representation for persistence and reporting."""
        payload = asdict(self)
        payload["detected_level"] = self.detected_level.value
        return payload


RESPONSE_JSON_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "seniority_match",
        "detected_level",
        "required_experience",
        "evidence",
        "reason",
    ],
    "properties": {
        "seniority_match": {"enum": [True, False, "uncertain"]},
        "detected_level": {"enum": [level.value for level in DetectedLevel]},
        "required_experience": {"type": "string", "maxLength": 200},
        "evidence": {"type": "string", "maxLength": 500},
        "reason": {"type": "string", "maxLength": 1000},
    },
}

_REQUIRED_FIELDS = frozenset(
    {
        "seniority_match",
        "detected_level",
        "required_experience",
        "evidence",
        "reason",
    }
)


def parse_seniority_response(content: str) -> SeniorityDecision:
    """Parse a JSON response and validate every field without coercion."""
    try:
        raw = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise SeniorityResponseError("seniority response must be valid JSON") from error
    if not isinstance(raw, Mapping):
        raise SeniorityResponseError("seniority response root must be an object")
    return seniority_decision_from_mapping(raw)


def seniority_decision_from_mapping(raw: Mapping[str, object]) -> SeniorityDecision:
    """Validate a parsed model response against the strict response contract."""
    fields = frozenset(raw)
    missing = sorted(_REQUIRED_FIELDS - fields)
    unexpected = sorted(fields - _REQUIRED_FIELDS)
    if missing:
        raise SeniorityResponseError(f"seniority response is missing fields: {', '.join(missing)}")
    if unexpected:
        raise SeniorityResponseError(
            f"seniority response has unexpected fields: {', '.join(unexpected)}"
        )

    match_value = raw["seniority_match"]
    if isinstance(match_value, bool):
        seniority_match: SeniorityMatch = match_value
    elif isinstance(match_value, str) and match_value == "uncertain":
        seniority_match = "uncertain"
    else:
        raise SeniorityResponseError("seniority_match must be true, false, or 'uncertain'")

    level_value = _bounded_string(raw["detected_level"], "detected_level", maximum=50)
    try:
        detected_level = DetectedLevel(level_value)
    except ValueError as error:
        allowed = ", ".join(level.value for level in DetectedLevel)
        raise SeniorityResponseError(f"detected_level must be one of: {allowed}") from error

    required_experience = _bounded_string(
        raw["required_experience"],
        "required_experience",
        maximum=200,
    )
    evidence = _bounded_string(raw["evidence"], "evidence", maximum=500)
    reason = _bounded_string(raw["reason"], "reason", maximum=1000)
    return SeniorityDecision(
        seniority_match=seniority_match,
        detected_level=detected_level,
        required_experience=required_experience,
        evidence=evidence,
        reason=reason,
    )


def _bounded_string(value: object, path: str, *, maximum: int) -> str:
    """Validate a model-supplied string and bound its length.

    Deliberately NOT core.validation.required_text. Two differences are load-bearing:
    it raises SeniorityResponseError rather than ValueError, so an invalid model response
    routes to manual review instead of crashing the scan; and it caps length, because this
    text comes from a language model and an unbounded field is an unbounded report row.

    This is the kind of divergence 6.4 warned about -- and the reason the consolidation
    was worth doing by hand rather than by a blanket rename.
    """
    if not isinstance(value, str) or not value.strip():
        raise SeniorityResponseError(f"{path} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise SeniorityResponseError(f"{path} must contain at most {maximum} characters")
    return normalized
