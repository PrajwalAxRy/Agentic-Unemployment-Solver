"""Tests for the reviewed seniority evaluation set."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from job_finder.matching.evaluation_set import load_seniority_evaluation_set
from job_finder.matching.seniority import DetectedLevel

EVALUATION_SET = Path("config/seniority_evaluation_set.json")


def test_reviewed_evaluation_set_preserves_all_h1_examples_and_categories() -> None:
    evaluation = load_seniority_evaluation_set(EVALUATION_SET)

    assert evaluation.set_version == "1.0.0"
    assert evaluation.profile_id == "india-ai-ml-under-five-years"
    assert [example.example_id for example in evaluation.examples] == [
        f"seniority-{index:02d}" for index in range(1, 21)
    ]
    assert Counter(example.expected_match for example in evaluation.examples) == {
        True: 12,
        False: 4,
        "uncertain": 4,
    }
    assert {example.expected_level for example in evaluation.examples} >= {
        DetectedLevel.ENTRY,
        DetectedLevel.JUNIOR,
        DetectedLevel.MID,
        DetectedLevel.SENIOR,
        DetectedLevel.LEAD,
        DetectedLevel.PRINCIPAL,
        DetectedLevel.UNKNOWN,
    }
    assert any("preferred" in example.description for example in evaluation.examples)
    assert any(
        "multiple engineering teams" in example.description for example in evaluation.examples
    )
    assert any("company has 10 years" in example.description for example in evaluation.examples)


def test_evidence_must_be_present_in_description(tmp_path: Path) -> None:
    payload = json.loads(EVALUATION_SET.read_text(encoding="utf-8"))
    payload["examples"][0]["important_evidence"] = "not in the description"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="must occur in the description"):
        load_seniority_evaluation_set(path)


def test_duplicate_example_ids_are_rejected(tmp_path: Path) -> None:
    payload = json.loads(EVALUATION_SET.read_text(encoding="utf-8"))
    payload["examples"][1]["id"] = payload["examples"][0]["id"]
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate seniority evaluation id"):
        load_seniority_evaluation_set(path)
