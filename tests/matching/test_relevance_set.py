"""The relevance evaluation set is valid and covers the documented failure modes.

The gate this measures decides what counts as an AI/ML job. ``to_change.md`` 2.3 replaces
a regex filter that ran ten times in an entire scan, so there is no meaningful prior
measurement to fall back on -- the eval set is the only thing standing between a prompt
change and a silent change in what the system considers relevant.

These tests check the set itself, not the model. They are fast, offline, and they fail if
someone removes a documented failure mode or lets a label drift away from its evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from job_finder.matching.relevance_set import (
    RelevanceVerdict,
    load_relevance_evaluation_set,
)

ROOT = Path(__file__).resolve().parents[2]
EVALUATION_SET = ROOT / "config" / "relevance_evaluation_set.json"


def test_shipped_evaluation_set_loads_and_validates() -> None:
    evaluation_set = load_relevance_evaluation_set(EVALUATION_SET)

    assert evaluation_set.schema_version == 1
    assert evaluation_set.profile_id == "india-ai-ml-under-five-years"
    assert len(evaluation_set.examples) >= 20


def test_every_verdict_is_represented() -> None:
    """A set with no peripheral cases cannot detect a gate collapsing to binary."""
    evaluation_set = load_relevance_evaluation_set(EVALUATION_SET)

    for verdict in RelevanceVerdict:
        assert evaluation_set.by_verdict(verdict), f"no {verdict.value} examples"

    # Negatives must not be an afterthought -- the four named failure modes are all
    # negatives, and a gate that passes everything is the failure being guarded against.
    negatives = evaluation_set.by_verdict(RelevanceVerdict.UNRELATED)
    assert len(negatives) >= 5


def test_the_four_documented_failure_modes_are_all_covered() -> None:
    """2.3 names four specific ways the old filter was fooled.

    Each is a real row from the 2026-09-29 scan. If one is dropped from the set, the gate
    can regress on it without any test noticing.
    """
    evaluation_set = load_relevance_evaluation_set(EVALUATION_SET)
    unrelated = evaluation_set.by_verdict(RelevanceVerdict.UNRELATED)
    corpus = " ".join(
        f"{item.title} {item.description} {item.human_rationale}" for item in unrelated
    ).casefold()

    # AI in the team name only (Ads AI Core Infra)
    assert "ads ai core infra" in corpus
    # AI as a tool the engineer uses
    assert "generative ai to improve team productivity" in corpus
    # AI-assisted development rather than AI products (the FBA rows)
    assert "generative ai coding assistants" in corpus
    # AI in the org blurb, absent from duties and quals (RBS Tech)
    assert "ai-first company" in corpus


def test_real_scan_rows_dominate_the_set() -> None:
    """Grounded in observed failures rather than invented ones."""
    evaluation_set = load_relevance_evaluation_set(EVALUATION_SET)

    from_scan = [item for item in evaluation_set.examples if item.source == "scan-2026-09-29"]
    assert len(from_scan) >= 12


def test_rows_that_reached_the_real_report_are_retained_as_positives() -> None:
    """Guard against over-correction.

    The obvious failure when tightening a filter is to fix the false positives and
    silently lose the true ones. These titles genuinely reached the 2026-09-29 report.
    """
    evaluation_set = load_relevance_evaluation_set(EVALUATION_SET)
    substantive_titles = {
        item.title for item in evaluation_set.by_verdict(RelevanceVerdict.SUBSTANTIVE)
    }

    assert "Software Engineer III - Python, AWS, GenAI" in substantive_titles
    assert "Sr. Data Scientist, Amazon Pay Data Products" in substantive_titles


def test_evidence_must_appear_in_its_description(tmp_path: Path) -> None:
    """A label whose evidence is not in the text is unfalsifiable."""
    broken = {
        "schema_version": 1,
        "set_version": "test",
        "profile_id": "test",
        "examples": [
            {
                "id": "bad-01",
                "title": "ML Engineer",
                "description": "Builds ranking models.",
                "expected_verdict": "substantive",
                "human_rationale": "Core modelling.",
                "important_evidence": "text that is absent from the description",
            }
        ],
    }
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(broken), encoding="utf-8")

    with pytest.raises(ValueError, match="important_evidence must occur verbatim"):
        load_relevance_evaluation_set(path)


def test_unknown_verdict_is_rejected(tmp_path: Path) -> None:
    payload = {
        "schema_version": 1,
        "set_version": "test",
        "profile_id": "test",
        "examples": [
            {
                "id": "bad-02",
                "title": "ML Engineer",
                "description": "Builds ranking models.",
                "expected_verdict": "maybe",
                "human_rationale": "Unclear.",
                "important_evidence": "Builds ranking models",
            }
        ],
    }
    path = tmp_path / "bad_verdict.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="expected_verdict must be one of"):
        load_relevance_evaluation_set(path)


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    example = {
        "id": "dup-01",
        "title": "ML Engineer",
        "description": "Builds ranking models.",
        "expected_verdict": "substantive",
        "human_rationale": "Core modelling.",
        "important_evidence": "Builds ranking models",
    }
    payload = {
        "schema_version": 1,
        "set_version": "test",
        "profile_id": "test",
        "examples": [example, dict(example)],
    }
    path = tmp_path / "dupes.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate relevance evaluation id"):
        load_relevance_evaluation_set(path)


def test_unsupported_schema_version_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "v2.json"
    path.write_text(json.dumps({"schema_version": 2, "examples": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported relevance evaluation schema_version"):
        load_relevance_evaluation_set(path)
