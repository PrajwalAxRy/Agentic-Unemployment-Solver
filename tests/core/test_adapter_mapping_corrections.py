"""Tests for deterministic source migrations found during adapter validation."""

from __future__ import annotations

from copy import deepcopy

import pytest

from job_finder.core.adapter_mapping_corrections import apply_adapter_mapping_corrections


def proposals() -> dict[str, object]:
    return {
        "proposals": [
            {
                "company_id": "company",
                "status": "conflict",
                "official_careers_url": "https://job-boards.greenhouse.io/embed/job_app",
                "adapter_type": "greenhouse",
                "adapter_parameters": {"board_token": "embed"},
                "evidence": [],
            }
        ]
    }


def corrections() -> dict[str, object]:
    return {
        "corrections": [
            {
                "company_id": "company",
                "url": "https://job-boards.greenhouse.io/company",
                "title": "Jobs at Company",
                "reason": "Corrected embedded URL parsing.",
            }
        ]
    }


def test_changed_mapping_becomes_proposed_without_mutating_input() -> None:
    original = proposals()
    revised = apply_adapter_mapping_corrections(original, corrections())
    proposal = revised["proposals"][0]

    assert original == proposals()
    assert proposal["status"] == "proposed"
    assert proposal["adapter_parameters"] == {"board_token": "company"}
    assert proposal["access_concern"] is None
    assert proposal["evidence"][-1]["evidence_type"] == "phase4_adapter_mapping_correction"


def test_reapplying_current_mapping_preserves_later_validation_fields() -> None:
    once = apply_adapter_mapping_corrections(proposals(), corrections())
    proposal = once["proposals"][0]
    proposal.update(
        status="auto_verified",
        publication_date_field="first_published",
        detail_strategy="listing_payload",
    )

    twice = apply_adapter_mapping_corrections(once, corrections())
    preserved = twice["proposals"][0]

    assert preserved["status"] == "auto_verified"
    assert preserved["publication_date_field"] == "first_published"
    assert preserved["detail_strategy"] == "listing_payload"
    assert len(preserved["evidence"]) == 1


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value["corrections"].append(deepcopy(value["corrections"][0])), "duplicate"),
        (lambda value: value["corrections"][0].update(company_id="missing"), "unknown"),
        (
            lambda value: value["corrections"][0].update(url="https://company.example/careers"),
            "not a supported hosted ATS",
        ),
    ],
)
def test_invalid_corrections_are_rejected(mutator, message: str) -> None:
    candidate = deepcopy(corrections())
    mutator(candidate)

    with pytest.raises(ValueError, match=message):
        apply_adapter_mapping_corrections(proposals(), candidate)
