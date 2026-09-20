"""Tests for guarded adapter-group evidence application."""

from __future__ import annotations

from copy import deepcopy

import pytest

from job_finder.core.adapter_validation import apply_ashby_validation, apply_greenhouse_validation


def proposals() -> dict[str, object]:
    return {
        "proposals": [
            {
                "company_id": "one",
                "adapter_type": "ashby",
                "adapter_parameters": {"board_name": "One Board"},
                "status": "proposed",
                "evidence": [],
            },
            {
                "company_id": "other",
                "adapter_type": "greenhouse",
                "adapter_parameters": {"board_token": "other"},
                "status": "auto_verified",
                "evidence": [],
            },
        ]
    }


def report(*, outcome: str = "success", complete: bool = True) -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at": "2026-09-20T12:00:00+05:30",
        "adapter_type": "ashby",
        "records": [
            {
                "company_id": "one",
                "adapter_type": "ashby",
                "outcome": outcome,
                "complete": complete,
                "job_count": 3,
                "page_count": 1,
                "missing_field_count": 0,
            }
        ],
    }


def test_complete_healthy_report_updates_only_ashby_sources() -> None:
    original = proposals()
    revised = apply_ashby_validation(original, report())
    ashby = revised["proposals"][0]

    assert original == proposals()
    assert ashby["status"] == "auto_verified"
    assert ashby["adapter_parameters"] == {"board_name": "One Board"}
    assert ashby["official_careers_url"].endswith("/One%20Board")
    assert ashby["publication_date_basis"] == "published"
    assert ashby["publication_date_verified"] is True
    assert len(ashby["evidence"]) == 2
    assert revised["proposals"][1] == original["proposals"][1]


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value["records"].clear(), "coverage mismatch"),
        (lambda value: value["records"][0].update(outcome="failed"), "not healthy"),
        (lambda value: value.update(adapter_type="greenhouse"), "target ashby"),
    ],
)
def test_incomplete_or_unhealthy_reports_are_rejected(mutator, message: str) -> None:
    candidate = deepcopy(report())
    mutator(candidate)

    with pytest.raises(ValueError, match=message):
        apply_ashby_validation(proposals(), candidate)


def greenhouse_report(*, outcome: str = "success", complete: bool = True) -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at": "2026-09-20T18:00:00+05:30",
        "adapter_type": "greenhouse",
        "records": [
            {
                "company_id": "other",
                "adapter_type": "greenhouse",
                "outcome": outcome,
                "complete": complete,
                "job_count": 4,
                "page_count": 1,
                "missing_field_count": 0,
                "date_basis_distribution": {"published": 3, "updated": 1, "unknown": 0},
            }
        ],
    }


def test_complete_greenhouse_report_records_date_fallback_evidence() -> None:
    original = proposals()
    revised = apply_greenhouse_validation(original, greenhouse_report())
    greenhouse = revised["proposals"][1]

    assert original == proposals()
    assert greenhouse["status"] == "auto_verified"
    assert greenhouse["official_careers_url"].endswith("/other")
    assert greenhouse["list_endpoint"].endswith("/other/jobs?content=true")
    assert greenhouse["publication_date_field"] == "first_published"
    assert greenhouse["publication_date_verified"] is True
    assert greenhouse["detail_strategy"] == "listing_payload"
    assert "updated_fallback=1" in greenhouse["evidence"][-1]["note"]
    assert revised["proposals"][0] == original["proposals"][0]


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value["records"].clear(), "coverage mismatch"),
        (lambda value: value["records"][0].update(complete=False), "not healthy"),
        (lambda value: value.update(adapter_type="ashby"), "target greenhouse"),
    ],
)
def test_incomplete_greenhouse_reports_are_rejected(mutator, message: str) -> None:
    candidate = deepcopy(greenhouse_report())
    mutator(candidate)

    with pytest.raises(ValueError, match=message):
        apply_greenhouse_validation(proposals(), candidate)
