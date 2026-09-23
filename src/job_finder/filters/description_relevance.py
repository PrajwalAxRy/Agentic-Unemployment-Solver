"""Deterministic substantive-AI-work gate for approved generic job titles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from job_finder.core.search_profile import ConditionalDescriptionPolicy
from job_finder.normalization.jobs import normalize_text, normalize_title

_SEGMENT_BOUNDARY = re.compile(r"(?:[.!?;]|[\r\n]+|[•●▪◦])+")
_ACTION_SUFFIXES = ("", "s", "ed", "ing", "ment", "ments", "tion", "tions")


class DescriptionRelevanceDecision(StrEnum):
    """Whether a conditional-title description proves substantive target work."""

    PASS = "pass"
    REJECT = "reject"
    REVIEW = "review"


@dataclass(frozen=True, slots=True)
class DescriptionRelevanceResult:
    """Explainable output from the deterministic conditional-description gate."""

    decision: DescriptionRelevanceDecision
    reason_code: str
    reason: str
    evidence: str | None = None
    matched_topic: str | None = None
    matched_action: str | None = None


def evaluate_substantive_ai_work(
    description: str | None,
    *,
    policy: ConditionalDescriptionPolicy,
) -> DescriptionRelevanceResult:
    """Require non-incidental AI/ML topic and substantive action evidence nearby."""
    if description is None or not normalize_text(description):
        return DescriptionRelevanceResult(
            decision=DescriptionRelevanceDecision.REVIEW,
            reason_code="missing_description",
            reason="conditional title cannot be assessed without a job description",
        )

    display_text = normalize_text(description)
    normalized_description = normalize_title(display_text)
    saw_incidental = any(
        _phrase_spans(normalized_description, normalize_title(term))
        for term in policy.incidental_only_terms
    )
    segments = tuple(
        segment for raw in _SEGMENT_BOUNDARY.split(description) if (segment := normalize_text(raw))
    )
    candidates = (*segments, *(_join_adjacent(segments)))
    saw_topic = False
    saw_non_incidental_topic = False
    saw_action = False
    for candidate in candidates:
        normalized = normalize_title(candidate)
        topics = _matched_terms(normalized, policy.ai_topic_terms)
        actions = _matched_actions(normalized, policy.substantive_action_terms)
        saw_action = saw_action or bool(actions)
        if not topics:
            continue
        saw_topic = True
        eligible_topics = tuple(
            topic
            for topic in topics
            if _has_non_incidental_occurrence(
                normalized,
                topic,
                policy.incidental_only_terms,
            )
        )
        if not eligible_topics:
            continue
        saw_non_incidental_topic = True
        if actions:
            return DescriptionRelevanceResult(
                decision=DescriptionRelevanceDecision.PASS,
                reason_code="substantive_ai_work",
                reason="description pairs an approved AI or ML topic with substantive work",
                evidence=_bounded_evidence(candidate),
                matched_topic=eligible_topics[0],
                matched_action=actions[0],
            )

    if saw_topic and not saw_non_incidental_topic:
        return DescriptionRelevanceResult(
            decision=DescriptionRelevanceDecision.REJECT,
            reason_code="incidental_ai_only",
            reason="AI or ML wording appears only in approved incidental contexts",
        )
    if not saw_topic and saw_incidental:
        return DescriptionRelevanceResult(
            decision=DescriptionRelevanceDecision.REJECT,
            reason_code="incidental_ai_only",
            reason="AI or ML wording appears only in approved incidental contexts",
        )
    if not saw_topic:
        return DescriptionRelevanceResult(
            decision=DescriptionRelevanceDecision.REJECT,
            reason_code="no_ai_topic",
            reason="description contains no approved AI or ML topic evidence",
        )
    if not saw_action:
        return DescriptionRelevanceResult(
            decision=DescriptionRelevanceDecision.REJECT,
            reason_code="no_substantive_action",
            reason="description mentions AI or ML without an approved substantive action",
        )
    return DescriptionRelevanceResult(
        decision=DescriptionRelevanceDecision.REJECT,
        reason_code="topic_action_not_connected",
        reason="AI or ML topics are not connected to substantive role responsibilities",
        evidence=_bounded_evidence(display_text),
    )


def _join_adjacent(segments: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"{left}. {right}" for left, right in zip(segments, segments[1:], strict=False))


def _matched_terms(value: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(term for term in terms if _phrase_spans(value, normalize_title(term)))


def _matched_actions(value: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    matches: list[str] = []
    for term in terms:
        normalized = normalize_title(term)
        if not normalized:
            continue
        if " " in normalized or normalized.endswith("e"):
            variants: tuple[str, ...] = (
                normalized,
                f"{normalized}s",
                f"{normalized}d",
                f"{normalized[:-1]}ing",
            )
        else:
            variants = tuple(f"{normalized}{suffix}" for suffix in _ACTION_SUFFIXES)
        if any(_phrase_spans(value, variant) for variant in variants):
            matches.append(term)
    return tuple(matches)


def _has_non_incidental_occurrence(
    value: str,
    topic: str,
    incidental_terms: tuple[str, ...],
) -> bool:
    topic_spans = _phrase_spans(value, normalize_title(topic))
    incidental_spans = tuple(
        span for term in incidental_terms for span in _phrase_spans(value, normalize_title(term))
    )
    return any(
        not any(
            start >= incidental_start and end <= incidental_end
            for incidental_start, incidental_end in incidental_spans
        )
        for start, end in topic_spans
    )


def _phrase_spans(value: str, phrase: str) -> tuple[tuple[int, int], ...]:
    if not phrase:
        return ()
    pattern = re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)")
    return tuple((match.start(), match.end()) for match in pattern.finditer(value))


def _bounded_evidence(value: str, *, limit: int = 320) -> str:
    normalized = normalize_text(value)
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"
