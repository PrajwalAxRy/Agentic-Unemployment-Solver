"""Tests for the deterministic substantive-AI-work description gate."""

from pathlib import Path

from job_finder.core.search_profile import load_search_profile
from job_finder.filters.description_relevance import (
    DescriptionRelevanceDecision,
    evaluate_substantive_ai_work,
)

POLICY = load_search_profile(Path("config/search_profile.toml")).conditional_description


def test_substantive_model_work_passes_with_evidence() -> None:
    result = evaluate_substantive_ai_work(
        "You will build and deploy production machine learning models for customer workflows.",
        policy=POLICY,
    )

    assert result.decision is DescriptionRelevanceDecision.PASS
    assert result.reason_code == "substantive_ai_work"
    assert result.matched_topic == "machine learning"
    assert result.matched_action == "build"
    assert result.evidence == (
        "You will build and deploy production machine learning models for customer workflows"
    )


def test_inflected_action_and_adjacent_topic_sentence_pass() -> None:
    result = evaluate_substantive_ai_work(
        "You will be designing reliable product services. These generative AI pipelines handle "
        "millions of requests.",
        policy=POLICY,
    )

    assert result.decision is DescriptionRelevanceDecision.PASS
    assert result.matched_action == "design"
    assert result.matched_topic == "generative ai"


def test_ai_powering_company_boilerplate_is_incidental() -> None:
    result = evaluate_substantive_ai_work(
        "We build an AI-powered company for modern commerce. You will develop payment APIs.",
        policy=POLICY,
    )

    assert result.decision is DescriptionRelevanceDecision.REJECT
    assert result.reason_code == "incidental_ai_only"


def test_use_of_ai_tools_is_incidental() -> None:
    result = evaluate_substantive_ai_work(
        "Use AI tools to develop conventional backend services and improve code quality.",
        policy=POLICY,
    )

    assert result.decision is DescriptionRelevanceDecision.REJECT
    assert result.reason_code == "incidental_ai_only"


def test_generic_technology_taxonomy_does_not_make_payment_development_ai_work() -> None:
    result = evaluate_substantive_ai_work(
        "Knowledge may span cloud, artificial intelligence, machine learning, mobile, and other "
        "technical disciplines. You will develop Tandem payment applications with COBOL.",
        policy=POLICY,
    )

    assert result.decision is DescriptionRelevanceDecision.REJECT
    assert result.reason_code == "incidental_ai_only"


def test_ai_coding_assistants_do_not_make_full_stack_development_ai_work() -> None:
    result = evaluate_substantive_ai_work(
        "As a Software Engineer II - Java Full Stack Developer + AWS + AI, you design and "
        "deliver conventional software components. Leverage enterprise-authorized AI coding "
        "assist tools to improve code quality. Apply knowledge of AI-assisted development and "
        "automation capabilities. Be proficient in using AI for tech tools such as Copilot, LLM, "
        "and Claude Code. Hands-on experience in Java, frontend, AWS, AI tools, and platform or "
        "product development is required. Use AI productivity tools for coding, testing, and "
        "documentation while validating AI-generated outputs and following responsible AI use.",
        policy=POLICY,
    )

    assert result.decision is DescriptionRelevanceDecision.REJECT
    assert result.reason_code == "incidental_ai_only"


def test_topic_without_substantive_action_is_rejected() -> None:
    result = evaluate_substantive_ai_work(
        "The team supports machine learning customers and answers platform questions.",
        policy=POLICY,
    )

    assert result.decision is DescriptionRelevanceDecision.REJECT
    assert result.reason_code == "no_substantive_action"


def test_action_without_target_topic_is_rejected() -> None:
    result = evaluate_substantive_ai_work(
        "Build and operate high-volume payment APIs using Python and PostgreSQL.",
        policy=POLICY,
    )

    assert result.decision is DescriptionRelevanceDecision.REJECT
    assert result.reason_code == "no_ai_topic"


def test_distant_unrelated_topic_and_action_do_not_pass() -> None:
    result = evaluate_substantive_ai_work(
        "The company uses machine learning models. This role supports payroll "
        "reporting. You will build tax-compliance APIs for finance users.",
        policy=POLICY,
    )

    assert result.decision is DescriptionRelevanceDecision.REJECT
    assert result.reason_code == "topic_action_not_connected"


def test_missing_description_remains_visible_for_review() -> None:
    result = evaluate_substantive_ai_work(None, policy=POLICY)

    assert result.decision is DescriptionRelevanceDecision.REVIEW
    assert result.reason_code == "missing_description"
