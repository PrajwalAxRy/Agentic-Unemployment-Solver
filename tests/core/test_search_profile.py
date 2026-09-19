"""Tests for the versioned search-profile contract."""

from __future__ import annotations

from copy import deepcopy

import pytest

from job_finder.core.search_profile import (
    DateUncertaintyMode,
    search_profile_from_mapping,
)


def valid_profile() -> dict[str, object]:
    return {
        "schema_version": 1,
        "profile_id": "india-ai-ml-under-five-years",
        "version": "0.1.0-proposed",
        "recency": {
            "window_days": 10,
            "date_uncertainty_mode": "measure_then_decide",
        },
        "roles": {
            "families": [
                {
                    "id": "machine-learning-engineering",
                    "label": "Machine learning engineering",
                    "title_terms": ["machine learning engineer", "ml engineer"],
                }
            ],
            "title_exclusions": [
                {
                    "term": "sales engineer",
                    "reason": "Commercial role without target engineering scope",
                }
            ],
        },
        "location": {
            "accepted_countries": ["India"],
            "city_aliases": {"Bengaluru": ["Bangalore", "Bengaluru"]},
            "accepted_work_modes": ["onsite", "hybrid", "remote"],
            "remote_requires_explicit_country": True,
            "multi_location_treatment": "accept_if_any_explicitly_allowed",
            "ambiguous_location_treatment": "review",
        },
        "seniority": {
            "maximum_exclusive_years": 5,
            "description": "Open to a qualified candidate with fewer than five years.",
            "ambiguity_treatment": "review",
        },
    }


def test_valid_profile_loads() -> None:
    profile = search_profile_from_mapping(valid_profile())

    assert profile.profile_id == "india-ai-ml-under-five-years"
    assert profile.recency_window_days == 10
    assert profile.date_uncertainty_mode is DateUncertaintyMode.MEASURE_THEN_DECIDE
    assert profile.role_families[0].family_id == "machine-learning-engineering"


@pytest.mark.parametrize("missing_key", ["roles", "location"])
def test_missing_required_policy_fails_clearly(missing_key: str) -> None:
    raw = valid_profile()
    del raw[missing_key]

    with pytest.raises(ValueError, match=missing_key):
        search_profile_from_mapping(raw)


def test_unknown_schema_version_reports_supported_version() -> None:
    raw = valid_profile()
    raw["schema_version"] = 2

    with pytest.raises(ValueError, match="supported=1"):
        search_profile_from_mapping(raw)


def test_equivalent_mapping_order_has_stable_hash() -> None:
    first = valid_profile()
    second = {key: deepcopy(first[key]) for key in reversed(first)}

    assert (
        search_profile_from_mapping(first).content_hash
        == search_profile_from_mapping(second).content_hash
    )


def test_meaningful_profile_change_changes_hash() -> None:
    first = valid_profile()
    second = deepcopy(first)
    seniority = second["seniority"]
    assert isinstance(seniority, dict)
    seniority["description"] = "A changed target definition."

    assert (
        search_profile_from_mapping(first).content_hash
        != search_profile_from_mapping(second).content_hash
    )


def test_first_release_boundaries_cannot_drift() -> None:
    raw = valid_profile()
    recency = raw["recency"]
    assert isinstance(recency, dict)
    recency["window_days"] = 30

    with pytest.raises(ValueError, match="must be 10"):
        search_profile_from_mapping(raw)
