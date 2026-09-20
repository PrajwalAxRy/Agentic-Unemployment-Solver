"""Deterministic corrections discovered during live adapter-family validation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from job_finder.core.search_discovery import infer_adapter


def load_adapter_mapping_corrections(path: Path) -> dict[str, object]:
    """Load the versioned Phase 4 adapter-mapping correction record."""
    with path.open("r", encoding="utf-8") as stream:
        payload: Any = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError("adapter mapping corrections must be a JSON object")
    if payload.get("schema_version") != 1:
        raise ValueError("adapter mapping corrections schema_version must be 1")
    if not isinstance(payload.get("corrections"), list):
        raise ValueError("adapter mapping corrections require a corrections array")
    return payload


def apply_adapter_mapping_corrections(
    proposal_payload: dict[str, object],
    correction_payload: Mapping[str, object],
) -> dict[str, object]:
    """Apply current hosted-ATS mappings without erasing later validation evidence."""
    revised = deepcopy(proposal_payload)
    proposals = revised.get("proposals")
    corrections = correction_payload.get("corrections")
    if not isinstance(proposals, list) or not isinstance(corrections, list):
        raise ValueError("proposal and correction payloads require arrays")
    proposal_by_id = {item.get("company_id"): item for item in proposals if isinstance(item, dict)}
    seen: set[str] = set()
    for raw in corrections:
        correction = _mapping(raw, "correction")
        company_id = _string(correction, "company_id", "correction")
        if company_id in seen:
            raise ValueError(f"duplicate correction company_id: {company_id}")
        seen.add(company_id)
        proposal = proposal_by_id.get(company_id)
        if not isinstance(proposal, dict):
            raise ValueError(f"adapter mapping correction has unknown company_id: {company_id}")
        url = _string(correction, "url", "correction")
        title = _string(correction, "title", "correction")
        reason = _string(correction, "reason", "correction")
        adapter_type, parameters, endpoint, listing_mode = infer_adapter(url)
        status = correction.get("status", "proposed")
        if status not in {"proposed", "conflict"}:
            raise ValueError(f"adapter mapping correction has invalid status: {company_id}")
        mapping_is_current = (
            proposal.get("official_careers_url") == url
            and proposal.get("adapter_type") == adapter_type
            and proposal.get("adapter_parameters") == parameters
        )
        if not mapping_is_current:
            proposal.update(
                {
                    "status": status,
                    "official_careers_url": url,
                    "regional_board_url": None,
                    "adapter_type": adapter_type,
                    "adapter_parameters": parameters,
                    "listing_mode": listing_mode,
                    "list_endpoint": endpoint,
                    "pagination": "Requires full adapter-group verification.",
                    "external_job_id_field": None,
                    "publication_date_field": None,
                    "publication_date_basis": "unknown",
                    "publication_date_verified": False,
                    "title_field": None,
                    "location_field": None,
                    "detail_strategy": "detail_page",
                    "confidence": "low" if status == "conflict" else "medium",
                    "access_concern": reason if status == "conflict" else None,
                    "notes": reason,
                }
            )
        evidence = proposal.setdefault("evidence", [])
        if not isinstance(evidence, list):
            raise ValueError(f"proposal evidence must be an array: {company_id}")
        item = {
            "url": url,
            "evidence_type": "phase4_adapter_mapping_correction",
            "note": title,
        }
        if item not in evidence:
            evidence.append(item)
    return revised


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    return value


def _string(raw: Mapping[str, object], key: str, path: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}.{key} must be a non-empty string")
    return value.strip()
