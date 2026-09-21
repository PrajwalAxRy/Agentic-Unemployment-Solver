"""Tests for the labelled search-policy examples approved at H1."""

from pathlib import Path

from job_finder.core.policy_examples import (
    LocationExampleDecision,
    RoleExampleDecision,
    SeniorityExampleDecision,
    load_policy_examples,
)


def test_approved_policy_examples_load() -> None:
    examples = load_policy_examples(Path("config/search_policy_examples.toml"))

    assert examples.profile_id == "india-ai-ml-under-five-years"
    assert examples.profile_version == "1.1.0"
    assert len(examples.role) == 14
    assert len(examples.location) == 15
    assert len(examples.seniority) == 20


def test_generic_titles_and_mixed_remote_feedback_are_recorded() -> None:
    examples = load_policy_examples(Path("config/search_policy_examples.toml"))
    role_by_title = {item.title: item.expected for item in examples.role}
    location_by_text = {item.source_location: item.expected for item in examples.location}

    assert role_by_title["Senior Software Engineer"] is RoleExampleDecision.CONDITIONAL_DESCRIPTION
    assert role_by_title["Data Scientist"] is RoleExampleDecision.CONDITIONAL_DESCRIPTION
    assert location_by_text["Singapore or Remote"] is LocationExampleDecision.PASS
    assert location_by_text["Remote"] is LocationExampleDecision.REVIEW


def test_seniority_boundaries_are_labelled() -> None:
    examples = load_policy_examples(Path("config/search_policy_examples.toml"))
    by_evidence = {item.evidence: item.expected for item in examples.seniority}

    assert (
        by_evidence["4+ years building production ML systems"] is SeniorityExampleDecision.INCLUDE
    )
    assert (
        by_evidence["5+ years of relevant experience required"] is SeniorityExampleDecision.EXCLUDE
    )
