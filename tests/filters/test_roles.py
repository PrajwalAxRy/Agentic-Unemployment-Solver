"""Tests for deterministic title filtering."""

from pathlib import Path

import pytest

from job_finder.core.policy_examples import load_policy_examples
from job_finder.core.search_profile import load_search_profile
from job_finder.filters.roles import RoleDecision, filter_role

PROFILE = load_search_profile(Path("config/search_profile.toml"))


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (example.title, RoleDecision(example.expected.value))
        for example in load_policy_examples(Path("config/search_policy_examples.toml")).role
    ],
)
def test_every_approved_role_example(title: str, expected: RoleDecision) -> None:
    assert filter_role(title, profile=PROFILE).decision is expected


def test_exclusion_takes_precedence_over_target_terms() -> None:
    result = filter_role("Senior Machine Learning Sales Engineer", profile=PROFILE)

    assert result.decision is RoleDecision.REJECT
    assert result.reason_code == "excluded_title"
    assert result.matched_term == "sales engineer"


@pytest.mark.parametrize(
    "title",
    [
        "AI/ML Engineer",
        "Gen AI Engineer",
        "Natural-Language-Processing Engineer",
        "Machine Learning Engineering Manager",
        "Lead Software Engineer - LLM Platform",
    ],
)
def test_common_variants_and_multi_role_titles_pass(title: str) -> None:
    result = filter_role(title, profile=PROFILE)

    assert result.decision is RoleDecision.EXPLICIT_PASS
    assert result.family_id is not None


def test_ambiguous_abbreviations_do_not_pass() -> None:
    assert filter_role("CV Engineer", profile=PROFILE).decision is RoleDecision.REJECT
    assert filter_role("MCP Engineer", profile=PROFILE).decision is RoleDecision.REJECT


def test_mcp_with_agent_context_passes() -> None:
    result = filter_role("AI Agent MCP Engineer", profile=PROFILE)

    assert result.decision is RoleDecision.EXPLICIT_PASS
    assert result.family_id == "agents_and_tooling"
