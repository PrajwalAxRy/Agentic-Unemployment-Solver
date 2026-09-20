"""Tests for guarded adapter-group evidence application."""

from __future__ import annotations

from copy import deepcopy

import pytest

from job_finder.core.adapter_validation import (
    apply_ashby_validation,
    apply_greenhouse_validation,
    apply_lever_validation,
    apply_workday_validation,
)


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
            {
                "company_id": "lever-company",
                "adapter_type": "lever",
                "adapter_parameters": {"site": "lever-company"},
                "status": "proposed",
                "evidence": [],
            },
            {
                "company_id": "workday-company",
                "adapter_type": "workday",
                "adapter_parameters": {
                    "host": "workday-company.wd1.myworkdayjobs.com",
                    "tenant": "workday-company",
                    "site": "External",
                },
                "status": "proposed",
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


def lever_report(*, outcome: str = "success", complete: bool = True) -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at": "2026-09-20T19:00:00+05:30",
        "adapter_type": "lever",
        "records": [
            {
                "company_id": "lever-company",
                "adapter_type": "lever",
                "outcome": outcome,
                "complete": complete,
                "job_count": 5,
                "page_count": 2,
                "missing_field_count": 1,
                "date_basis_distribution": {"published": 0, "updated": 0, "unknown": 5},
            }
        ],
    }


def test_complete_lever_report_records_uncertain_date_and_missing_field_evidence() -> None:
    original = proposals()
    revised = apply_lever_validation(original, lever_report())
    lever = revised["proposals"][2]

    assert original == proposals()
    assert lever["status"] == "auto_verified"
    assert lever["official_careers_url"].endswith("/lever-company")
    assert lever["list_endpoint"].endswith("/lever-company?mode=json")
    assert lever["publication_date_field"] == "createdAt"
    assert lever["publication_date_basis"] == "unknown"
    assert lever["publication_date_verified"] is False
    assert "missing_fields=1" in lever["evidence"][-1]["note"]
    assert "unknown_dates=5" in lever["evidence"][-1]["note"]


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value["records"].clear(), "coverage mismatch"),
        (lambda value: value["records"][0].update(outcome="partial"), "not healthy"),
        (lambda value: value.update(adapter_type="greenhouse"), "target lever"),
    ],
)
def test_incomplete_lever_reports_are_rejected(mutator, message: str) -> None:
    candidate = deepcopy(lever_report())
    mutator(candidate)

    with pytest.raises(ValueError, match=message):
        apply_lever_validation(proposals(), candidate)


def workday_report(*, outcome: str = "success", complete: bool = True) -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at": "2026-09-20T20:00:00+05:30",
        "adapter_type": "workday",
        "records": [
            {
                "company_id": "workday-company",
                "adapter_type": "workday",
                "outcome": outcome,
                "complete": complete,
                "job_count": 21,
                "page_count": 2,
                "missing_field_count": 1,
                "date_basis_distribution": {
                    "published": 0,
                    "updated": 0,
                    "first_seen": 0,
                    "unknown": 21,
                },
            }
        ],
    }


def test_complete_workday_report_records_pagination_and_uncertain_date_evidence() -> None:
    original = proposals()
    revised = apply_workday_validation(original, workday_report())
    workday = revised["proposals"][3]

    assert original == proposals()
    assert workday["status"] == "auto_verified"
    assert workday["official_careers_url"].endswith("/External")
    assert workday["list_endpoint"].endswith("/workday-company/External/jobs")
    assert workday["publication_date_field"] == "postedOn"
    assert workday["publication_date_basis"] == "unknown"
    assert workday["publication_date_verified"] is False
    assert workday["detail_strategy"] == "detail_endpoint"
    assert "missing_fields=1" in workday["evidence"][-1]["note"]
    assert "unknown_dates=21" in workday["evidence"][-1]["note"]


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value["records"].clear(), "coverage mismatch"),
        (lambda value: value["records"][0].update(outcome="suspicious"), "not healthy"),
        (lambda value: value.update(adapter_type="lever"), "target workday"),
    ],
)
def test_incomplete_workday_reports_are_rejected(mutator, message: str) -> None:
    candidate = deepcopy(workday_report())
    mutator(candidate)

    with pytest.raises(ValueError, match=message):
        apply_workday_validation(proposals(), candidate)
