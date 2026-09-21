"""Deterministic India eligibility and work-mode filtering."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from job_finder.core.job_contracts import NormalizedJob
from job_finder.core.search_profile import LocationPolicy
from job_finder.normalization.jobs import normalize_location_values, normalize_text, normalize_title

_MISSING_LOCATION_VALUES = frozenset(
    {"location unavailable", "location not available", "not specified", "unknown", "n a", "na"}
)
_AMBIGUOUS_REGIONS = (
    "apac",
    "asia",
    "emea",
    "global",
    "worldwide",
    "anywhere",
)
_WORK_MODES = ("onsite", "on site", "hybrid", "remote")


class LocationDecision(StrEnum):
    """Approved pre-description location outcomes."""

    PASS = "pass"
    REVIEW = "review"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class LocationFilterResult:
    """Explainable India-location decision."""

    decision: LocationDecision
    reason_code: str
    reason: str
    matched_locations: tuple[str, ...] = ()
    work_modes: tuple[str, ...] = ()


def filter_job_location(job: NormalizedJob, *, policy: LocationPolicy) -> LocationFilterResult:
    """Filter the normalized location and structured metadata for one job."""
    return filter_location(
        job.location_original,
        normalized_locations=job.location_normalized,
        source_metadata=job.source_metadata,
        policy=policy,
    )


def filter_location(
    location_original: str | None,
    *,
    normalized_locations: Sequence[str] | None = None,
    source_metadata: Mapping[str, object] | None = None,
    policy: LocationPolicy,
) -> LocationFilterResult:
    """Determine whether public pre-description evidence establishes India eligibility."""
    metadata = source_metadata or {}
    locations = tuple(normalized_locations or ())
    if not locations and location_original:
        locations = normalize_location_values(location_original, policy=policy)

    normalized = tuple(normalize_title(value) for value in locations if value.strip())
    raw_normalized = normalize_title(location_original or "")
    work_modes = _work_modes(raw_normalized, metadata)

    structured_country = _structured_country(metadata)
    if structured_country in {"in", "ind", "india", "republic of india"}:
        return LocationFilterResult(
            decision=LocationDecision.PASS,
            reason_code="structured_india_country",
            reason="structured source country explicitly allows India",
            matched_locations=(structured_country,),
            work_modes=work_modes,
        )

    allowed_locations = _allowed_locations(normalized, policy)
    if allowed_locations:
        if not _modes_allowed(work_modes, policy):
            return LocationFilterResult(
                decision=LocationDecision.REJECT,
                reason_code="work_mode_not_allowed",
                reason="location passes but the source work mode is not accepted",
                matched_locations=allowed_locations,
                work_modes=work_modes,
            )
        return LocationFilterResult(
            decision=LocationDecision.PASS,
            reason_code="accepted_india_location",
            reason="at least one explicit location is in India",
            matched_locations=allowed_locations,
            work_modes=work_modes,
        )

    if _has_unqualified_remote_alternative(
        location_original, normalized
    ) and policy.accept_unqualified_remote_alternative:
        return LocationFilterResult(
            decision=LocationDecision.PASS,
            reason_code="unqualified_remote_alternative",
            reason="remote is offered as a separate unrestricted location alternative",
            matched_locations=("remote",),
            work_modes=work_modes or ("remote",),
        )

    if _is_missing(normalized, raw_normalized, metadata):
        return LocationFilterResult(
            decision=LocationDecision.REVIEW,
            reason_code="missing_location",
            reason="source location is missing and cannot establish India eligibility",
            work_modes=work_modes,
        )

    if _has_explicit_foreign_remote_scope(location_original):
        return LocationFilterResult(
            decision=LocationDecision.REJECT,
            reason_code="remote_outside_india",
            reason="remote work is explicitly restricted to a non-India geography",
            work_modes=work_modes,
        )

    if _has_ambiguous_geography(normalized, raw_normalized) or "remote" in work_modes:
        return LocationFilterResult(
            decision=LocationDecision.REVIEW,
            reason_code="ambiguous_location",
            reason="remote or regional evidence does not explicitly establish India eligibility",
            work_modes=work_modes,
        )

    return LocationFilterResult(
        decision=LocationDecision.REJECT,
        reason_code="outside_india",
        reason="all explicit locations are outside India",
        work_modes=work_modes,
    )


def _allowed_locations(
    normalized_locations: tuple[str, ...], policy: LocationPolicy
) -> tuple[str, ...]:
    accepted_names = {
        normalize_title(name)
        for name in (*policy.city_aliases.keys(), *policy.region_aliases.keys())
    }
    for aliases in (*policy.city_aliases.values(), *policy.region_aliases.values()):
        accepted_names.update(normalize_title(alias) for alias in aliases)
    accepted_countries = {
        normalize_title(country)
        for country in policy.accepted_countries
        if normalize_title(country) not in {"in", "ind"}
    }
    matches: list[str] = []
    for location in normalized_locations:
        if any(_contains_phrase(location, value) for value in accepted_names | accepted_countries):
            matches.append(location)
    return tuple(dict.fromkeys(matches))


def _structured_country(metadata: Mapping[str, object]) -> str | None:
    for key in (
        "country",
        "country_code",
        "primary_location_country",
        "location_country",
    ):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return normalize_text(value).casefold()
    return None


def _work_modes(raw_location: str, metadata: Mapping[str, object]) -> tuple[str, ...]:
    modes: list[str] = []
    for term in _WORK_MODES:
        if _contains_phrase(raw_location, normalize_title(term)):
            canonical = "onsite" if term in {"onsite", "on site"} else term
            if canonical not in modes:
                modes.append(canonical)
    for key in ("workplace_type", "work_location_option"):
        value = metadata.get(key)
        if isinstance(value, str):
            normalized = normalize_title(value)
            for term in _WORK_MODES:
                if _contains_phrase(normalized, normalize_title(term)):
                    canonical = "onsite" if term in {"onsite", "on site"} else term
                    if canonical not in modes:
                        modes.append(canonical)
    if (
        metadata.get("is_remote") is True or metadata.get("remote") is True
    ) and "remote" not in modes:
        modes.append("remote")
    if metadata.get("hybrid") is True and "hybrid" not in modes:
        modes.append("hybrid")
    return tuple(modes)


def _modes_allowed(work_modes: tuple[str, ...], policy: LocationPolicy) -> bool:
    return not work_modes or all(mode in policy.accepted_work_modes for mode in work_modes)


def _has_unqualified_remote_alternative(
    original: str | None, normalized_locations: tuple[str, ...]
) -> bool:
    if original and re.search(r"(?:\bor\b|[|;/])\s*remote\b", original, flags=re.IGNORECASE):
        return not re.search(
            r"remote\s*[-:,]?\s*(?:apac|asia|emea|global|worldwide|us|usa|united states|canada|"
            r"europe|uk|united kingdom|singapore)\b",
            original,
            flags=re.IGNORECASE,
        )
    return "remote" in normalized_locations and len(normalized_locations) > 1


def _has_explicit_foreign_remote_scope(original: str | None) -> bool:
    if not original:
        return False
    return bool(
        re.search(
            r"remote\s*[-:,]?\s*(?:us|usa|united states|canada|europe|uk|united kingdom|"
            r"singapore|australia|new zealand)\b",
            original,
            flags=re.IGNORECASE,
        )
    )


def _is_missing(
    normalized_locations: tuple[str, ...],
    raw_normalized: str,
    metadata: Mapping[str, object],
) -> bool:
    if metadata.get("listing_location_missing") is True:
        return True
    if not raw_normalized or not normalized_locations:
        return True
    return all(value in _MISSING_LOCATION_VALUES for value in normalized_locations)


def _has_ambiguous_geography(
    normalized_locations: tuple[str, ...], raw_normalized: str
) -> bool:
    combined = " ".join((*normalized_locations, raw_normalized))
    return any(_contains_phrase(combined, term) for term in (*_AMBIGUOUS_REGIONS, "remote"))


def _contains_phrase(value: str, phrase: str) -> bool:
    return bool(phrase) and f" {phrase} " in f" {value} "
