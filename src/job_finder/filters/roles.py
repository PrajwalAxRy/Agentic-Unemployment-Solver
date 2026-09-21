"""Deterministic role-family and title-exclusion filtering."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from job_finder.core.search_profile import SearchProfile
from job_finder.normalization.jobs import normalize_title

_TITLE_TOPIC_TERMS = (
    "graph neural network",
    "predictive ai",
    "machine learning",
    "artificial intelligence",
    "computer vision",
    "natural language processing",
    "generative ai",
    "model context protocol",
    "ai agents",
    "ai agent",
    "agentic ai",
    "enterprise search",
    "vector search",
    "search",
    "retrieval",
    "embedding",
    "genai",
    "llm",
    "nlp",
    "rag",
    "ml",
    "ai",
)


class RoleDecision(StrEnum):
    """Pre-description role-filter outcomes."""

    EXPLICIT_PASS = "explicit_pass"
    CONDITIONAL_DESCRIPTION = "conditional_description"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class RoleFilterResult:
    """Explainable title decision used by reports and later pipeline stages."""

    decision: RoleDecision
    reason_code: str
    reason: str
    family_id: str | None = None
    matched_term: str | None = None


def filter_role(title: str, *, profile: SearchProfile) -> RoleFilterResult:
    """Classify one title using the approved exclusion-first two-lane policy."""
    normalized = normalize_title(title)
    if not normalized:
        return RoleFilterResult(
            decision=RoleDecision.REJECT,
            reason_code="missing_title",
            reason="title is empty after normalization",
        )

    exclusion = _matching_exclusion(normalized, profile)
    if exclusion is not None:
        return RoleFilterResult(
            decision=RoleDecision.REJECT,
            reason_code="excluded_title",
            reason=exclusion.reason,
            matched_term=exclusion.term,
        )

    for family in profile.role_families:
        for term in family.title_terms:
            if _contains_phrase(normalized, normalize_title(term)):
                return RoleFilterResult(
                    decision=RoleDecision.EXPLICIT_PASS,
                    reason_code="accepted_role_family",
                    reason=f"accepted role family {family.label}",
                    family_id=family.family_id,
                    matched_term=term,
                )

    generic_term = next(
        (
            term
            for term in profile.conditional_description.title_terms
            if _contains_phrase(normalized, normalize_title(term))
        ),
        None,
    )
    topic = _matching_topic(normalized, profile)
    if generic_term is not None:
        if topic is not None:
            family_id = _topic_family(normalized, topic)
            return RoleFilterResult(
                decision=RoleDecision.EXPLICIT_PASS,
                reason_code="generic_title_with_target_qualifier",
                reason="generic role has an explicit AI or ML title qualifier",
                family_id=family_id,
                matched_term=topic,
            )
        return RoleFilterResult(
            decision=RoleDecision.CONDITIONAL_DESCRIPTION,
            reason_code="conditional_description_required",
            reason="approved generic title requires substantive AI or ML description evidence",
            matched_term=generic_term,
        )

    if _is_engineering_role(normalized) and topic is not None:
        return RoleFilterResult(
            decision=RoleDecision.EXPLICIT_PASS,
            reason_code="engineering_title_with_target_qualifier",
            reason="engineering role has an explicit AI or ML title qualifier",
            family_id=_topic_family(normalized, topic),
            matched_term=topic,
        )

    return RoleFilterResult(
        decision=RoleDecision.REJECT,
        reason_code="no_target_role_family",
        reason="title does not match an approved target or conditional role family",
    )


def _matching_exclusion(normalized: str, profile: SearchProfile):  # type: ignore[no-untyped-def]
    for exclusion in profile.title_exclusions:
        if _contains_phrase(normalized, normalize_title(exclusion.term)):
            return exclusion
    tokens = set(normalized.split())
    if "evaluator" in tokens and tokens.intersection({"ai", "ml", "model"}):
        return next(
            (
                item
                for item in profile.title_exclusions
                if item.term in {"ai evaluator", "model evaluator"}
            ),
            None,
        )
    return None


def _matching_topic(normalized: str, profile: SearchProfile) -> str | None:
    topics = (*_TITLE_TOPIC_TERMS, *profile.conditional_description.ai_topic_terms)
    for topic in sorted(topics, key=lambda value: len(normalize_title(value)), reverse=True):
        normalized_topic = normalize_title(topic)
        if normalized_topic == "model context protocol":
            if _contains_phrase(normalized, normalized_topic):
                return topic
            continue
        if normalized_topic == "ai" and not _contains_token(normalized, "ai"):
            continue
        if normalized_topic == "ml" and not _contains_token(normalized, "ml"):
            continue
        if _contains_phrase(normalized, normalized_topic):
            return topic
    return None


def _topic_family(normalized: str, topic: str) -> str:
    topic_text = normalize_title(topic)
    combined = f"{normalized} {topic_text}"
    if any(
        _contains_phrase(combined, term)
        for term in ("agent", "agentic ai", "model context protocol")
    ):
        return "agents_and_tooling"
    if any(
        _contains_phrase(combined, term)
        for term in ("rag", "retrieval", "search", "embedding", "vector database")
    ):
        return "retrieval_search_and_rag"
    if any(
        _contains_phrase(combined, term)
        for term in ("inference", "model serving", "quantize", "compiler", "optimization")
    ):
        return "model_systems_and_optimization"
    if any(
        _contains_phrase(combined, term)
        for term in ("platform", "infrastructure", "mlops", "ml ops", "ml pipeline")
    ):
        return "ml_platform_and_infrastructure"
    if any(token in normalized.split() for token in ("scientist", "research")):
        return "research_and_applied_science"
    if any(
        _contains_phrase(combined, term)
        for term in (
            "large language model",
            "llm",
            "generative ai",
            "genai",
            "foundation model",
            "conversational ai",
        )
    ):
        return "generative_ai_engineering"
    if any(
        _contains_phrase(combined, term)
        for term in ("deep learning", "computer vision", "natural language processing", "nlp")
    ):
        return "ml_engineering"
    return "ai_software_and_product_engineering"


def _is_engineering_role(normalized: str) -> bool:
    tokens = set(normalized.split())
    return bool(tokens.intersection({"engineer", "engineering", "architect"}))


def _contains_phrase(value: str, phrase: str) -> bool:
    return bool(phrase) and f" {phrase} " in f" {value} "


def _contains_token(value: str, token: str) -> bool:
    return token in value.split()
