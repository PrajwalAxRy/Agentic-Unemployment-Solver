"""Tests for sanitized, inactive source-repair artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from job_finder.core.company_registry import load_company_registry
from job_finder.repair import (
    RepairChangeType,
    RepairConfidence,
    RepairRequest,
    build_repair_request,
    load_repair_request,
    preview_registry_with_proposal,
    validate_repair_proposal,
    write_repair_artifact,
)

ROOT = Path(__file__).resolve().parents[1]


def verification_payload() -> dict[str, object]:
    return {
        "schema_version": 2,
        "generated_at": "2026-09-23T12:00:00+05:30",
        "registry_version": "0.2.0-phase4",
        "adapter_type": "greenhouse",
        "baseline_generated_at": "2026-09-22T12:00:00+05:30",
        "company_count": 1,
        "outcome_counts": {"suspicious": 1},
        "failure_category_counts": {"schema_change": 1},
        "anomaly_counts": {"result_count_collapse": 1},
        "records": [
            {
                "company_id": "glean",
                "company_name": "Glean",
                "source_rank": 1,
                "priority": "P1",
                "adapter_type": "greenhouse",
                "configuration_version": "0.2.0-phase4",
                "outcome": "suspicious",
                "complete": False,
                "job_count": 0,
                "page_count": 1,
                "missing_field_count": 0,
                "date_basis_distribution": {},
                "exception_categories": ["result_count_collapse"],
                "failure_categories": ["schema_change"],
                "anomaly_categories": ["result_count_collapse"],
                "attempt_count": 3,
                "sample_job_urls": [],
            }
        ],
    }


def proposal_payload(proposal_id: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "proposal_id": proposal_id,
        "company_id": "glean",
        "proposer_model": "synthetic-test-model",
        "summary": "Update the reviewed public board identifier.",
        "change_type": "company_parameter",
        "confidence": "medium",
        "rationale": "The current public endpoint returns a count collapse.",
        "changes": [
            {
                "path": "sources[glean].adapter_parameters.board_token",
                "before": "gleanwork",
                "after": "glean-public",
            }
        ],
        "fixture_test_plan": ["Add a saved response for the new public board."],
        "live_test_plan": ["Run targeted verification for Glean."],
        "rollback_plan": ["Restore board_token to gleanwork."],
        "activation_status": "inactive",
    }


def build_request(tmp_path: Path) -> RepairRequest:
    verification = tmp_path / "verification.json"
    verification.write_text(json.dumps(verification_payload()), encoding="utf-8")
    return build_repair_request(
        load_company_registry(ROOT / "config" / "company_sources.json"),
        verification,
        company_id="glean",
    )


def test_repair_request_contains_only_sanitized_failure_evidence(tmp_path: Path) -> None:
    request = build_request(tmp_path)
    output = tmp_path / "request.json"
    write_repair_artifact(request, output)
    text = output.read_text(encoding="utf-8")

    assert request.proposal_id.startswith("repair-")
    assert request.adapter_parameters == {"board_token": "gleanwork"}
    assert request.evidence.failure_categories == ("schema_change",)
    assert request.evidence.anomaly_categories == ("result_count_collapse",)
    assert any("checkpoint H11" in item for item in request.constraints)
    assert "description" not in text
    assert "cookie" not in text.casefold()
    assert "authorization" not in text.casefold()

    loaded = load_repair_request(output)
    assert loaded == request


def test_validated_proposal_remains_inactive_and_has_test_and_rollback_plans(
    tmp_path: Path,
) -> None:
    request = build_request(tmp_path)

    proposal = validate_repair_proposal(request, proposal_payload(request.proposal_id))

    assert proposal.activation_status == "inactive"
    assert proposal.change_type is RepairChangeType.COMPANY_PARAMETER
    assert proposal.confidence is RepairConfidence.MEDIUM
    assert proposal.fixture_test_plan
    assert proposal.live_test_plan
    assert proposal.rollback_plan


def test_repair_proposal_cannot_claim_activation_or_target_another_request(
    tmp_path: Path,
) -> None:
    request = build_request(tmp_path)
    active = proposal_payload(request.proposal_id)
    active["activation_status"] = "active"
    with pytest.raises(ValueError, match="must remain inactive"):
        validate_repair_proposal(request, active)

    mismatched = proposal_payload("repair-another")
    with pytest.raises(ValueError, match="proposal_id does not match"):
        validate_repair_proposal(request, mismatched)


def test_repair_proposal_rejects_sensitive_values_and_noop_changes(tmp_path: Path) -> None:
    request = build_request(tmp_path)
    sensitive = proposal_payload(request.proposal_id)
    sensitive["changes"] = [
        {
            "path": "headers.authorization",
            "before": None,
            "after": "api_key=do-not-store-this",
        }
    ]
    with pytest.raises(ValueError, match="sensitive-data marker"):
        validate_repair_proposal(request, sensitive)

    noop = proposal_payload(request.proposal_id)
    noop["changes"] = [
        {
            "path": "sources[glean].adapter_parameters.board_token",
            "before": "gleanwork",
            "after": "gleanwork",
        }
    ]
    with pytest.raises(ValueError, match="must change the value"):
        validate_repair_proposal(request, noop)


def test_healthy_verification_cannot_generate_repair_request(tmp_path: Path) -> None:
    payload = verification_payload()
    records = payload["records"]
    assert isinstance(records, list)
    record = records[0]
    assert isinstance(record, dict)
    record["outcome"] = "empty"
    record["complete"] = True
    verification = tmp_path / "healthy.json"
    verification.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unhealthy or suspicious"):
        build_repair_request(
            load_company_registry(ROOT / "config" / "company_sources.json"),
            verification,
            company_id="glean",
        )


def test_inactive_proposal_preview_never_mutates_the_active_registry(tmp_path: Path) -> None:
    registry = load_company_registry(ROOT / "config" / "company_sources.json")
    request = build_request(tmp_path)
    proposal = validate_repair_proposal(request, proposal_payload(request.proposal_id))

    preview = preview_registry_with_proposal(registry, request, proposal)
    active_source = next(
        item.source for item in registry.entries if item.source.company_id == "glean"
    )
    preview_source = next(
        item.source for item in preview.entries if item.source.company_id == "glean"
    )

    assert active_source.adapter_parameters["board_token"] == "gleanwork"
    assert preview_source.adapter_parameters["board_token"] == "glean-public"
    assert registry.registry_version == "0.2.0-phase4"
    assert preview.registry_version.endswith("-preview")


def test_inactive_preview_rejects_a_stale_before_value(tmp_path: Path) -> None:
    registry = load_company_registry(ROOT / "config" / "company_sources.json")
    request = build_request(tmp_path)
    raw = proposal_payload(request.proposal_id)
    changes = raw["changes"]
    assert isinstance(changes, list)
    change = changes[0]
    assert isinstance(change, dict)
    change["before"] = "stale-board-name"
    proposal = validate_repair_proposal(request, raw)

    with pytest.raises(ValueError, match="does not match active value"):
        preview_registry_with_proposal(registry, request, proposal)
