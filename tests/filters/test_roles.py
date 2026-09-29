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
    """These survive the title stage -- but as conditional, never as an outright pass.

    2.2: no title may grant a pass or skip the relevance gate. The family label is still
    attached for reporting, it just no longer decides anything.
    """
    result = filter_role(title, profile=PROFILE)

    assert result.decision is RoleDecision.CONDITIONAL_DESCRIPTION
    assert result.family_id is not None


def test_no_title_can_skip_the_description_gate() -> None:
    """The single most important property of the new title stage (2.2).

    'DevOps Engineer II, Ads AI Core Infra' is the row that motivated this: under the old
    policy a bare 'AI' token anywhere granted an unconditional pass, so a pure DevOps role
    in a team called 'Ads AI Core Infra' skipped the description check entirely.
    """
    for title in (
        "Senior Machine Learning Engineer",
        "DevOps Engineer II, Ads AI Core Infra",
        "Staff Data Scientist - Graph Neural Networks & Predictive AI",
        "Backend Engineer - Search",
    ):
        result = filter_role(title, profile=PROFILE)
        assert result.decision is not RoleDecision.EXPLICIT_PASS, (
            f"{title!r} skipped the relevance gate; no title may do that"
        )


def test_engineering_abbreviations_now_reach_the_description_gate() -> None:
    """Recall gain from 2.2a: the old allowlist rejected these outright.

    Whether 'CV' means computer vision or curriculum vitae, and what 'MCP' refers to, are
    description questions. Rejecting them on the title guaranteed a silent false negative,
    and a false negative here is invisible while a false positive costs one skim.
    """
    assert (
        filter_role("CV Engineer", profile=PROFILE).decision is RoleDecision.CONDITIONAL_DESCRIPTION
    )
    assert (
        filter_role("MCP Engineer", profile=PROFILE).decision
        is RoleDecision.CONDITIONAL_DESCRIPTION
    )


def test_mcp_with_agent_context_keeps_its_family_label() -> None:
    result = filter_role("AI Agent MCP Engineer", profile=PROFILE)

    assert result.decision is RoleDecision.CONDITIONAL_DESCRIPTION
    assert result.family_id == "agents_and_tooling"


def test_non_engineering_functions_are_still_rejected() -> None:
    """The blocklist half: reject functions, not domains (2.2a)."""
    for title in ("Recruiting Coordinator", "Account Executive", "Warehouse Associate"):
        assert filter_role(title, profile=PROFILE).decision is RoleDecision.REJECT, title


def test_domain_words_do_not_reject_engineering_roles() -> None:
    """2.2a's serious failure mode: domain-vs-function confusion.

    Every one of these is a real title that a naive blocklist rejected on a business-domain
    word. The engineering-function check must take precedence over the blocklist.
    """
    for title in (
        "Software Dev Engineer II, AWS Healthcare AI",
        "Software Dev Engineer II, Amazon Marketing Cloud",
        "Software Development Engineer, Amazon Customer Service",
        "Security Engineer, Security for Employee and Legal Systems",
        "Machine Learning Engineer, Prime Video Ads CX",
        "Software Development Engineer II, Enterprise Engineering",
    ):
        assert filter_role(title, profile=PROFILE).decision is not RoleDecision.REJECT, title
