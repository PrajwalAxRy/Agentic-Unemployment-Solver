"""Tests for provisional source discovery and guarded registry import."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from job_finder.core.company_seed import CompanySeedRecord
from job_finder.core.source_contracts import SourceStatus
from job_finder.core.source_discovery import (
    audit_discovery_batch,
    load_discovery_batch,
    proposal_to_disabled_source,
)


def proposal(company_id: str, company_name: str, source_rank: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "company_id": company_id,
        "company_name": company_name,
        "source_rank": source_rank,
        "priority": "P1",
        "status": "auto_verified",
        "official_careers_url": f"https://job-boards.greenhouse.io/{company_id}",
        "regional_board_url": None,
        "adapter_type": "greenhouse",
        "adapter_parameters": {"board_token": company_id},
        "listing_mode": "complete_list",
        "list_endpoint": f"https://boards-api.greenhouse.io/v1/boards/{company_id}/jobs",
        "pagination": "complete public board response",
        "external_job_id_field": "id",
        "publication_date_field": "updated_at",
        "publication_date_basis": "updated",
        "publication_date_verified": False,
        "title_field": "title",
        "location_field": "location.name",
        "detail_strategy": "listing_payload",
        "confidence": "high",
        "evidence": [
            {
                "url": f"https://job-boards.greenhouse.io/{company_id}",
                "evidence_type": "public_board",
                "note": "Public company-labelled board.",
            }
        ],
        "access_concern": None,
        "notes": "Provisional until H2 approval.",
    }


def write_batch(path: Path, proposals: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "batch_id": "test-batch",
                "discovered_at": "2026-09-20T12:00:00+05:30",
                "proposals": proposals,
            }
        ),
        encoding="utf-8",
    )


def seed(company_id: str, company_name: str, source_rank: int) -> CompanySeedRecord:
    return CompanySeedRecord(
        company_id=company_id,
        company_name=company_name,
        priority="P1",
        careers_url_hint=f"https://example.com/search/{company_id}",
        source_rank=source_rank,
    )


def test_complete_discovery_batch_reconciles_to_seed(tmp_path: Path) -> None:
    path = tmp_path / "batch.json"
    write_batch(path, [proposal("alpha", "Alpha", 1), proposal("beta", "Beta", 2)])

    batch = load_discovery_batch(path)
    audit = audit_discovery_batch(batch, [seed("alpha", "Alpha", 1), seed("beta", "Beta", 2)])

    assert audit.reconciled is True
    assert audit.seed_total == 2
    assert audit.proposal_total == 2
    assert audit.by_adapter == {"greenhouse": 2}
    assert audit.by_confidence == {"high": 2}


def test_batch_audit_reports_missing_extra_and_mismatched_rows(tmp_path: Path) -> None:
    path = tmp_path / "batch.json"
    write_batch(path, [proposal("alpha", "Wrong Alpha", 7), proposal("extra", "Extra", 2)])

    audit = audit_discovery_batch(
        load_discovery_batch(path),
        [seed("alpha", "Alpha", 1), seed("missing", "Missing", 2)],
    )

    assert audit.reconciled is False
    assert audit.missing_company_ids == ("missing",)
    assert audit.extra_company_ids == ("extra",)
    assert audit.name_mismatches == ("alpha",)
    assert audit.source_rank_mismatches == ("alpha",)


def test_proposal_import_is_disabled_and_requires_review(tmp_path: Path) -> None:
    path = tmp_path / "batch.json"
    write_batch(path, [proposal("alpha", "Alpha", 1)])

    source = proposal_to_disabled_source(load_discovery_batch(path).proposals[0])

    assert source.status is SourceStatus.PROPOSED
    assert source.enabled is False
    assert source.low_confidence_approved is False


def test_auto_verified_proposal_requires_public_evidence(tmp_path: Path) -> None:
    path = tmp_path / "batch.json"
    invalid = proposal("alpha", "Alpha", 1)
    invalid["evidence"] = []
    write_batch(path, [invalid])

    with pytest.raises(ValueError, match="requires an official URL and evidence"):
        load_discovery_batch(path)


def test_duplicate_proposal_company_id_fails(tmp_path: Path) -> None:
    path = tmp_path / "batch.json"
    write_batch(path, [proposal("alpha", "Alpha", 1), proposal("alpha", "Alpha", 1)])

    with pytest.raises(ValueError, match="duplicate company IDs"):
        load_discovery_batch(path)
