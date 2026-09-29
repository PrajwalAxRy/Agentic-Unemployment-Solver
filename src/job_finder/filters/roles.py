"""Deterministic role-family and title-exclusion filtering."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from job_finder.core.search_profile import SearchProfile
from job_finder.filters.title_classifier import classify as classify_title
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
    """Classify one title as an engineering discipline, or reject it (2.2, 2.2a).

    **Title decides discipline; description decides domain.** There is no AI-specific
    logic in this stage at all, and no title can grant a pass or skip the relevance gate.

    The old policy was generous in the wrong direction: strict on real ML roles whose
    titles do not say "AI" ("SDE, Ranking Platform" was rejected, never fetched, never
    seen), and loose on anything containing "AI" as a token -- including a team name. That
    is how "DevOps Engineer II, Ads AI Core Infra" got an unconditional pass and skipped
    the description check entirely.

    So the allowlist becomes a blocklist. Any engineering or technical IC role passes;
    only non-engineering *functions* are rejected. Everything that survives goes to the
    LLM relevance gate, which sees the description and can tell a team name from the work.

    Role families are retained as **labels** (``family_id``) rather than gates: useful
    report metadata and a seed for later domain classification, but they no longer decide
    anything.

    Volume: this raises the pass rate from 11% to roughly 70-79%, which is why 2.1 (run
    location first) had to land before it and why decision E sequenced it after the rate
    limiter.
    """
    normalized = normalize_title(title)
    if not normalized:
        return RoleFilterResult(
            decision=RoleDecision.REJECT,
            reason_code="missing_title",
            reason="title is empty after normalization",
        )

    # Profile-configured exclusions stay: cheap, correct, and independently reviewed
    # ("data labeler", "ai evaluator"). Checked first so configuration still wins.
    exclusion = _matching_exclusion(normalized, profile)
    if exclusion is not None:
        return RoleFilterResult(
            decision=RoleDecision.REJECT,
            reason_code="excluded_title",
            reason=exclusion.reason,
            matched_term=exclusion.term,
        )

    decision, reason_code, matched_term = classify_title(title)
    family_id = _family_label(normalized, profile)

    if decision == "reject":
        return RoleFilterResult(
            decision=RoleDecision.REJECT,
            reason_code=reason_code,
            reason=_REJECT_REASONS.get(reason_code, "title is not an engineering role"),
            family_id=family_id,
            matched_term=matched_term,
        )

    # Every surviving title is CONDITIONAL_DESCRIPTION: the description decides. Nothing
    # skips the relevance gate, so EXPLICIT_PASS is no longer reachable from a title.
    return RoleFilterResult(
        decision=RoleDecision.CONDITIONAL_DESCRIPTION,
        reason_code=reason_code,
        reason=_PASS_REASONS.get(reason_code, "engineering title requires description evidence"),
        family_id=family_id,
        matched_term=matched_term,
    )


_PASS_REASONS = {
    "engineering_function": (
        "engineering or technical role; the description decides AI or ML relevance"
    ),
    "ambiguous_no_function_word": (
        "no clear engineering function word; passed for the description gate to judge"
    ),
}

_REJECT_REASONS = {
    "missing_title": "title is empty after normalization",
    "hard_exclusion": "role performs annotation or evaluation work rather than building systems",
    "non_engineering_function": "title names a non-engineering business function",
    "domain_qualifier_only": "title names a business domain with no technical noun",
}


def _family_label(normalized: str, profile: SearchProfile) -> str | None:
    """Return a role-family label for reporting.

    Families are kept as metadata, not gates (2.2). They are the seed for a future domain
    classifier and they make the report readable; they no longer decide anything.
    """
    for family in profile.role_families:
        for term in family.title_terms:
            if _contains_phrase(normalized, normalize_title(term)):
                return family.family_id
    topic = _matching_topic(normalized, profile)
    if topic is not None:
        return _topic_family(normalized, topic)
    return None


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
