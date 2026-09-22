"""Tests for the strict seniority response contract."""

from __future__ import annotations

import json

import pytest

from job_finder.matching.seniority import (
    RESPONSE_JSON_SCHEMA,
    DetectedLevel,
    SeniorityResponseError,
    parse_seniority_response,
    seniority_decision_from_mapping,
)


def valid_response(*, match: bool | str = True) -> dict[str, object]:
    return {
        "seniority_match": match,
        "detected_level": "mid",
        "required_experience": "3+ years required",
        "evidence": "3+ years of relevant machine learning experience",
        "reason": "The required minimum is below five years.",
    }


def test_valid_match_response_is_normalized_and_serializable() -> None:
    decision = parse_seniority_response(json.dumps(valid_response()))

    assert decision.seniority_match is True
    assert decision.detected_level is DetectedLevel.MID
    assert decision.as_json() == valid_response()
    assert RESPONSE_JSON_SCHEMA["additionalProperties"] is False


def test_valid_rejection_response() -> None:
    raw = valid_response(match=False)
    raw["detected_level"] = "senior"
    raw["required_experience"] = "5+ years required"
    raw["reason"] = "The required minimum is not below five years."

    decision = seniority_decision_from_mapping(raw)

    assert decision.seniority_match is False
    assert decision.detected_level is DetectedLevel.SENIOR


def test_valid_uncertain_response() -> None:
    raw = valid_response(match="uncertain")
    raw["detected_level"] = "unknown"
    raw["required_experience"] = "unknown"
    raw["evidence"] = "Build and operate scalable machine learning systems"
    raw["reason"] = "The description gives no eligibility boundary or clear level."

    decision = seniority_decision_from_mapping(raw)

    assert decision.seniority_match == "uncertain"
    assert decision.detected_level is DetectedLevel.UNKNOWN


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("not-json", "valid JSON"),
        ("[]", "root must be an object"),
    ],
)
def test_malformed_payload_is_rejected(content: str, message: str) -> None:
    with pytest.raises(SeniorityResponseError, match=message):
        parse_seniority_response(content)


def test_missing_and_unexpected_fields_are_rejected() -> None:
    missing = valid_response()
    del missing["evidence"]
    unexpected = {**valid_response(), "confidence": 0.9}

    with pytest.raises(SeniorityResponseError, match="missing fields: evidence"):
        seniority_decision_from_mapping(missing)
    with pytest.raises(SeniorityResponseError, match="unexpected fields: confidence"):
        seniority_decision_from_mapping(unexpected)


@pytest.mark.parametrize("value", [1, 0, "true", None, "UNCERTAIN"])
def test_match_field_is_not_coerced(value: object) -> None:
    raw = valid_response()
    raw["seniority_match"] = value

    with pytest.raises(SeniorityResponseError, match="true, false, or 'uncertain'"):
        seniority_decision_from_mapping(raw)


def test_unknown_level_and_blank_or_oversized_evidence_are_rejected() -> None:
    bad_level = valid_response()
    bad_level["detected_level"] = "vice_president"
    blank_evidence = valid_response()
    blank_evidence["evidence"] = "   "
    long_evidence = valid_response()
    long_evidence["evidence"] = "x" * 501

    with pytest.raises(SeniorityResponseError, match="detected_level must be one of"):
        seniority_decision_from_mapping(bad_level)
    with pytest.raises(SeniorityResponseError, match="evidence must be a non-empty"):
        seniority_decision_from_mapping(blank_evidence)
    with pytest.raises(SeniorityResponseError, match="at most 500"):
        seniority_decision_from_mapping(long_evidence)
