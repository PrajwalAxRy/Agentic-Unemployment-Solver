"""Versioned search-profile contract."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from job_finder.core.hashing import configuration_hash

SUPPORTED_SEARCH_PROFILE_SCHEMA_VERSION = 1


class DateUncertaintyMode(StrEnum):
    """Supported publication-date policy states."""

    MEASURE_THEN_DECIDE = "measure_then_decide"
    EXCLUDE = "exclude"
    SEPARATE = "separate"
    FIRST_SEEN_FORWARD = "first_seen_forward"
    HYBRID = "hybrid"


class MultiLocationTreatment(StrEnum):
    """How a posting containing multiple locations is interpreted."""

    ACCEPT_IF_ANY_EXPLICITLY_ALLOWED = "accept_if_any_explicitly_allowed"
    REQUIRE_ALL_ALLOWED = "require_all_allowed"
    REVIEW_MIXED = "review_mixed"


class AmbiguousLocationTreatment(StrEnum):
    """How missing or ambiguous location evidence is handled."""

    REJECT = "reject"
    REVIEW = "review"


@dataclass(frozen=True, slots=True)
class RoleFamily:
    """A named target role family and its deterministic title terms."""

    family_id: str
    label: str
    title_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TitleExclusion:
    """A title term that takes precedence over a broad accepted term."""

    term: str
    reason: str


@dataclass(frozen=True, slots=True)
class ConditionalDescriptionPolicy:
    """Generic titles that require deterministic AI-work evidence from the description."""

    title_terms: tuple[str, ...]
    ai_topic_terms: tuple[str, ...]
    substantive_action_terms: tuple[str, ...]
    incidental_only_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LocationPolicy:
    """Deterministic geography and work-mode policy."""

    accepted_countries: tuple[str, ...]
    city_aliases: Mapping[str, tuple[str, ...]]
    region_aliases: Mapping[str, tuple[str, ...]]
    accepted_work_modes: tuple[str, ...]
    remote_requires_explicit_country: bool
    accept_unqualified_remote_alternative: bool
    multi_location_treatment: MultiLocationTreatment
    ambiguous_location_treatment: AmbiguousLocationTreatment


@dataclass(frozen=True, slots=True)
class SeniorityTarget:
    """Plain-language boundary passed to the later LLM evaluator."""

    maximum_exclusive_years: int
    description: str
    ambiguity_treatment: str


@dataclass(frozen=True, slots=True)
class SearchProfile:
    """Validated product behavior independent of any job source."""

    schema_version: int
    profile_id: str
    version: str
    recency_window_days: int
    date_uncertainty_mode: DateUncertaintyMode
    role_families: tuple[RoleFamily, ...]
    title_exclusions: tuple[TitleExclusion, ...]
    conditional_description: ConditionalDescriptionPolicy
    location: LocationPolicy
    seniority: SeniorityTarget
    content_hash: str


def load_search_profile(path: Path) -> SearchProfile:
    """Load and validate a TOML search profile."""
    with path.open("rb") as stream:
        raw: dict[str, object] = tomllib.load(stream)
    return search_profile_from_mapping(raw)


def search_profile_from_mapping(raw: Mapping[str, object]) -> SearchProfile:
    """Validate a search profile from parsed configuration content."""
    schema_version = _required_int(raw, "schema_version", "search profile")
    if schema_version != SUPPORTED_SEARCH_PROFILE_SCHEMA_VERSION:
        msg = (
            "unsupported search profile schema_version: "
            f"{schema_version}; supported={SUPPORTED_SEARCH_PROFILE_SCHEMA_VERSION}"
        )
        raise ValueError(msg)

    profile_id = _required_string(raw, "profile_id", "search profile")
    version = _required_string(raw, "version", "search profile")

    recency = _required_mapping(raw, "recency", "search profile")
    recency_window_days = _required_int(recency, "window_days", "recency")
    if recency_window_days != 10:
        msg = "recency.window_days must be 10 for the approved first release"
        raise ValueError(msg)
    date_uncertainty_mode = _enum_value(
        DateUncertaintyMode,
        _required_string(recency, "date_uncertainty_mode", "recency"),
        "recency.date_uncertainty_mode",
    )

    roles = _required_mapping(raw, "roles", "search profile")
    role_families = _parse_role_families(roles)
    title_exclusions = _parse_title_exclusions(roles)
    conditional_description = _parse_conditional_description(roles)

    location = _parse_location(_required_mapping(raw, "location", "search profile"))
    seniority = _parse_seniority(_required_mapping(raw, "seniority", "search profile"))

    return SearchProfile(
        schema_version=schema_version,
        profile_id=profile_id,
        version=version,
        recency_window_days=recency_window_days,
        date_uncertainty_mode=date_uncertainty_mode,
        role_families=role_families,
        title_exclusions=title_exclusions,
        conditional_description=conditional_description,
        location=location,
        seniority=seniority,
        content_hash=configuration_hash(raw),
    )


def _parse_role_families(roles: Mapping[str, object]) -> tuple[RoleFamily, ...]:
    items = _required_list(roles, "families", "roles")
    if not items:
        raise ValueError("roles.families must contain at least one role family")

    families: list[RoleFamily] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(items):
        path = f"roles.families[{index}]"
        family = _as_mapping(item, path)
        family_id = _required_string(family, "id", path)
        if family_id in seen_ids:
            raise ValueError(f"duplicate role family id: {family_id}")
        seen_ids.add(family_id)
        families.append(
            RoleFamily(
                family_id=family_id,
                label=_required_string(family, "label", path),
                title_terms=_required_string_tuple(family, "title_terms", path),
            )
        )
    return tuple(families)


def _parse_title_exclusions(roles: Mapping[str, object]) -> tuple[TitleExclusion, ...]:
    items = _required_list(roles, "title_exclusions", "roles")
    exclusions: list[TitleExclusion] = []
    for index, item in enumerate(items):
        path = f"roles.title_exclusions[{index}]"
        exclusion = _as_mapping(item, path)
        exclusions.append(
            TitleExclusion(
                term=_required_string(exclusion, "term", path),
                reason=_required_string(exclusion, "reason", path),
            )
        )
    return tuple(exclusions)


def _parse_conditional_description(
    roles: Mapping[str, object],
) -> ConditionalDescriptionPolicy:
    policy = _required_mapping(roles, "conditional_description", "roles")
    return ConditionalDescriptionPolicy(
        title_terms=_required_string_tuple(policy, "title_terms", "roles.conditional_description"),
        ai_topic_terms=_required_string_tuple(
            policy,
            "ai_topic_terms",
            "roles.conditional_description",
        ),
        substantive_action_terms=_required_string_tuple(
            policy,
            "substantive_action_terms",
            "roles.conditional_description",
        ),
        incidental_only_terms=_required_string_tuple(
            policy,
            "incidental_only_terms",
            "roles.conditional_description",
        ),
    )


def _parse_location(location: Mapping[str, object]) -> LocationPolicy:
    city_aliases = _parse_aliases(location, "city_aliases")
    region_aliases = _parse_aliases(location, "region_aliases")

    work_modes = _required_string_tuple(location, "accepted_work_modes", "location")
    unknown_work_modes = set(work_modes) - {"onsite", "hybrid", "remote"}
    if unknown_work_modes:
        values = ", ".join(sorted(unknown_work_modes))
        raise ValueError(f"location.accepted_work_modes contains unknown values: {values}")

    remote_requires_explicit_country = location.get("remote_requires_explicit_country")
    if not isinstance(remote_requires_explicit_country, bool):
        raise ValueError("location.remote_requires_explicit_country must be a boolean")
    accept_unqualified_remote_alternative = location.get("accept_unqualified_remote_alternative")
    if not isinstance(accept_unqualified_remote_alternative, bool):
        raise ValueError("location.accept_unqualified_remote_alternative must be a boolean")

    return LocationPolicy(
        accepted_countries=_required_string_tuple(location, "accepted_countries", "location"),
        city_aliases=city_aliases,
        region_aliases=region_aliases,
        accepted_work_modes=work_modes,
        remote_requires_explicit_country=remote_requires_explicit_country,
        accept_unqualified_remote_alternative=accept_unqualified_remote_alternative,
        multi_location_treatment=_enum_value(
            MultiLocationTreatment,
            _required_string(location, "multi_location_treatment", "location"),
            "location.multi_location_treatment",
        ),
        ambiguous_location_treatment=_enum_value(
            AmbiguousLocationTreatment,
            _required_string(location, "ambiguous_location_treatment", "location"),
            "location.ambiguous_location_treatment",
        ),
    )


def _parse_aliases(
    location: Mapping[str, object],
    key: str,
) -> Mapping[str, tuple[str, ...]]:
    aliases_raw = _required_mapping(location, key, "location")
    aliases: dict[str, tuple[str, ...]] = {}
    for canonical_name, values in aliases_raw.items():
        if not isinstance(canonical_name, str) or not canonical_name.strip():
            raise ValueError(f"location.{key} keys must be non-empty strings")
        aliases[canonical_name] = _string_tuple(values, f"location.{key}.{canonical_name}")
    if not aliases:
        raise ValueError(f"location.{key} must contain at least one alias group")
    return aliases


def _parse_seniority(seniority: Mapping[str, object]) -> SeniorityTarget:
    maximum_exclusive_years = _required_int(
        seniority,
        "maximum_exclusive_years",
        "seniority",
    )
    if maximum_exclusive_years != 5:
        raise ValueError("seniority.maximum_exclusive_years must be 5")
    ambiguity_treatment = _required_string(seniority, "ambiguity_treatment", "seniority")
    if ambiguity_treatment != "review":
        raise ValueError("seniority.ambiguity_treatment must be 'review'")
    return SeniorityTarget(
        maximum_exclusive_years=maximum_exclusive_years,
        description=_required_string(seniority, "description", "seniority"),
        ambiguity_treatment=ambiguity_treatment,
    )


def _required_mapping(
    raw: Mapping[str, object],
    key: str,
    path: str,
) -> Mapping[str, object]:
    value = raw.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{path}.{key} must be a table")
    return value


def _as_mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be a table")
    return value


def _required_list(raw: Mapping[str, object], key: str, path: str) -> list[object]:
    value = raw.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{path}.{key} must be an array")
    return value


def _required_string(raw: Mapping[str, object], key: str, path: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}.{key} must be a non-empty string")
    return value.strip()


def _required_int(raw: Mapping[str, object], key: str, path: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{path}.{key} must be an integer")
    return value


def _required_string_tuple(raw: Mapping[str, object], key: str, path: str) -> tuple[str, ...]:
    return _string_tuple(raw.get(key), f"{path}.{key}")


def _string_tuple(value: object, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{path} must be a non-empty array of strings")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{path} must contain only non-empty strings")
    return tuple(item.strip() for item in value if isinstance(item, str))


def _enum_value[EnumType: StrEnum](
    enum_type: type[EnumType],
    value: str,
    path: str,
) -> EnumType:
    try:
        return enum_type(value)
    except ValueError as error:
        supported = ", ".join(item.value for item in enum_type)
        raise ValueError(f"{path} must be one of: {supported}") from error
