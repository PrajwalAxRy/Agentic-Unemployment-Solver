"""Tests for guarded adapter-group evidence application."""

from __future__ import annotations

from copy import deepcopy

import pytest

from job_finder.core.adapter_validation import apply_ashby_validation


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
