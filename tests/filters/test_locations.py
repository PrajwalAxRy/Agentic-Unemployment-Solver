"""Tests for deterministic India-location filtering."""

from pathlib import Path

import pytest

from job_finder.core.policy_examples import load_policy_examples
from job_finder.core.search_profile import load_search_profile
from job_finder.filters.locations import LocationDecision, filter_location

PROFILE = load_search_profile(Path("config/search_profile.toml"))


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        (example.source_location, LocationDecision(example.expected.value))
        for example in load_policy_examples(Path("config/search_policy_examples.toml")).location
    ],
)
def test_every_approved_location_example(
    location: str | None, expected: LocationDecision
) -> None:
    result = filter_location(location, policy=PROFILE.location)

    assert result.decision is expected


def test_structured_india_country_code_passes() -> None:
    result = filter_location(
        "Remote",
        source_metadata={"country": "IN", "workplace_type": "remote"},
        policy=PROFILE.location,
    )

    assert result.decision is LocationDecision.PASS
    assert result.reason_code == "structured_india_country"


def test_free_text_in_is_not_treated_as_india() -> None:
    result = filter_location("IN", policy=PROFILE.location)

    assert result.decision is LocationDecision.REJECT


def test_multiple_locations_pass_when_any_is_in_india() -> None:
    result = filter_location(
        "Toronto | Hyderabad | London",
        normalized_locations=("toronto", "hyderabad", "london"),
        policy=PROFILE.location,
    )

    assert result.decision is LocationDecision.PASS
    assert result.matched_locations == ("hyderabad",)


@pytest.mark.parametrize(
    "location",
    ["Remote - United States", "London / Toronto", "Singapore"],
)
def test_explicit_non_india_locations_do_not_pass(location: str) -> None:
    assert filter_location(location, policy=PROFILE.location).decision is LocationDecision.REJECT


@pytest.mark.parametrize("location", ["Remote - APAC", "Worldwide", "Asia", "Remote"])
def test_ambiguous_remote_and_region_locations_require_review(location: str) -> None:
    assert filter_location(location, policy=PROFILE.location).decision is LocationDecision.REVIEW
