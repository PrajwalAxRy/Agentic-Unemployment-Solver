"""Apply explicit quality corrections after read-only source verification."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from job_finder.core.search_discovery import infer_adapter


def load_quality_corrections(path: Path) -> dict[str, object]:
    """Load the versioned quality-audit decisions used before H2."""
    with path.open("r", encoding="utf-8") as stream:
        raw: Any = json.load(stream)
    if not isinstance(raw, dict):
        raise ValueError("source quality corrections must be a JSON object")
    if raw.get("schema_version") != 1:
        raise ValueError("source quality corrections schema_version must be 1")
    return raw


def apply_quality_corrections(
    proposal_payload: dict[str, object],
    correction_payload: Mapping[str, object],
) -> dict[str, object]:
    """Replace supported candidates and downgrade suspicious matches to conflicts."""
    proposals = proposal_payload.get("proposals")
    replacements = correction_payload.get("replacements")
    downgrades = correction_payload.get("downgrades")
    if not isinstance(proposals, list):
        raise ValueError("proposal payload.proposals must be an array")
    if not isinstance(replacements, list) or not isinstance(downgrades, list):
        raise ValueError("quality corrections require replacements and downgrades arrays")
    proposal_by_id = {item.get("company_id"): item for item in proposals if isinstance(item, dict)}
    replacement_ids: set[str] = set()
    for raw in replacements:
        correction = _mapping(raw, "replacement")
        company_id = _string(correction, "company_id", "replacement")
        if company_id in replacement_ids:
            raise ValueError(f"duplicate replacement company_id: {company_id}")
        replacement_ids.add(company_id)
        proposal = _proposal(proposal_by_id, company_id)
        url = _string(correction, "url", "replacement")
        title = _string(correction, "title", "replacement")
        reason = _string(correction, "reason", "replacement")
        adapter, parameters, endpoint, listing_mode = infer_adapter(url)
        same_candidate = proposal.get("official_careers_url") == url or _has_evidence_url(
            proposal, url
        )
        preserve_probe_status = same_candidate and proposal.get("status") in {
            "auto_verified",
            "access_concern",
            "conflict",
            "proposed",
        }
        status = proposal.get("status") if preserve_probe_status else "proposed"
        confidence = proposal.get("confidence") if preserve_probe_status else "medium"
        access_concern = proposal.get("access_concern") if preserve_probe_status else None
        proposal.update(
            {
                "status": status,
                "official_careers_url": url,
                "regional_board_url": None,
                "adapter_type": adapter,
                "adapter_parameters": parameters,
                "listing_mode": listing_mode,
                "list_endpoint": endpoint,
                "pagination": "Requires adapter verification after H2 source approval.",
                "external_job_id_field": None,
                "publication_date_field": None,
                "publication_date_basis": "unknown",
                "publication_date_verified": False,
                "title_field": None,
                "location_field": None,
                "detail_strategy": "detail_page",
                "confidence": confidence,
                "access_concern": access_concern,
                "notes": reason,
            }
        )
        _append_evidence(proposal, url, "quality_correction_candidate", title)

    downgrade_ids: set[str] = set()
    for raw in downgrades:
        correction = _mapping(raw, "downgrade")
        company_id = _string(correction, "company_id", "downgrade")
        if company_id in downgrade_ids:
            raise ValueError(f"duplicate downgrade company_id: {company_id}")
        if company_id in replacement_ids:
            raise ValueError(f"company cannot be both replaced and downgraded: {company_id}")
        downgrade_ids.add(company_id)
        proposal = _proposal(proposal_by_id, company_id)
        reason = _string(correction, "reason", "downgrade")
        proposal.update(
            {
                "status": "conflict",
                "confidence": "low",
                "access_concern": reason,
                "notes": "Automated quality audit rejected this source for enablement.",
            }
        )
    return proposal_payload


def _append_evidence(
    proposal: dict[str, object],
    url: str,
    evidence_type: str,
    note: str,
) -> None:
    evidence = proposal.setdefault("evidence", [])
    if not isinstance(evidence, list):
        raise ValueError("proposal.evidence must be an array")
    item = {"url": url, "evidence_type": evidence_type, "note": note}
    if item not in evidence:
        evidence.append(item)


def _has_evidence_url(proposal: Mapping[str, object], url: str) -> bool:
    evidence = proposal.get("evidence")
    return isinstance(evidence, list) and any(
        isinstance(item, Mapping) and item.get("url") == url for item in evidence
    )


def _proposal(
    proposals: Mapping[object, object],
    company_id: str,
) -> dict[str, object]:
    proposal = proposals.get(company_id)
    if not isinstance(proposal, dict):
        raise ValueError(f"quality correction has unknown company_id: {company_id}")
    return proposal


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    return value


def _string(raw: Mapping[str, object], key: str, path: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}.{key} must be a non-empty string")
    return value.strip()
