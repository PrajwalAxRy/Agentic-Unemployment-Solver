"""Apply sanitized live-probe evidence to provisional discovery proposals."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from urllib.parse import unquote, urlsplit


def apply_verification_results(
    proposal_payload: dict[str, Any],
    verification_payload: dict[str, Any],
) -> dict[str, Any]:
    """Return a revised proposal payload without enabling any source."""
    revised = deepcopy(proposal_payload)
    proposals = revised.get("proposals")
    results = verification_payload.get("results")
    if not isinstance(proposals, list) or not isinstance(results, list):
        raise ValueError("proposal and verification payloads require result arrays")
    proposals_by_id = {item.get("company_id"): item for item in proposals if isinstance(item, dict)}
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("verification result must be an object")
        company_id = result.get("company_id")
        proposal = proposals_by_id.get(company_id)
        if not isinstance(company_id, str) or not isinstance(proposal, dict):
            raise ValueError(f"verification result has unknown company_id: {company_id!r}")
        probes = result.get("probes")
        if not isinstance(probes, list) or not probes:
            raise ValueError(f"verification result has no probes: {company_id}")
        _apply_company_result(proposal, probes)
    return revised


def _apply_company_result(proposal: dict[str, Any], probes: list[object]) -> None:
    adapter_type = proposal.get("adapter_type")
    list_endpoint = proposal.get("list_endpoint")
    normalized_probes = [probe for probe in probes if isinstance(probe, dict)]
    list_probe = next(
        (probe for probe in normalized_probes if probe.get("requested_url") == list_endpoint),
        normalized_probes[-1],
    )
    outcome = list_probe.get("outcome")

    if adapter_type in {"greenhouse", "ashby", "lever"}:
        if outcome == "success":
            proposal["status"] = "auto_verified"
            _add_probe_evidence(proposal, list_probe, "structured_list_probe")
        elif outcome == "response_too_large" and list_probe.get("status_code") == 200:
            proposal["status"] = "proposed"
            proposal["notes"] = (
                "Public structured endpoint responded but exceeded the bounded discovery probe; "
                "adapter verification must stream or page it."
            )
            _add_probe_evidence(proposal, list_probe, "bounded_probe_limit")
        else:
            _mark_conflict(proposal, list_probe)
        return

    first_probe = normalized_probes[0]
    final_url = first_probe.get("final_url")
    if isinstance(final_url, str) and ".myworkdayjobs.com/" in final_url:
        _apply_workday_redirect(proposal, first_probe, final_url)
        return
    if first_probe.get("outcome") == "success":
        proposal["status"] = "auto_verified"
        proposal["confidence"] = "medium"
        if isinstance(final_url, str):
            proposal["official_careers_url"] = final_url
            proposal["list_endpoint"] = final_url
            proposal["adapter_parameters"] = {"search_url": final_url}
        _add_probe_evidence(proposal, first_probe, "public_careers_page_probe")
    elif first_probe.get("outcome") == "access_block":
        proposal["status"] = "access_concern"
        proposal["confidence"] = "low"
        proposal["access_concern"] = (
            "Public probe encountered login, CAPTCHA, or access-control text."
        )
        _add_probe_evidence(proposal, first_probe, "access_concern_probe")
    else:
        _mark_conflict(proposal, first_probe)


def _apply_workday_redirect(
    proposal: dict[str, Any],
    probe: dict[str, Any],
    final_url: str,
) -> None:
    parsed = urlsplit(final_url)
    tenant = (parsed.hostname or "").split(".", maxsplit=1)[0]
    path_segments = [unquote(item) for item in parsed.path.split("/") if item]
    if not tenant or not path_segments:
        _mark_conflict(proposal, probe)
        return
    proposal.update(
        {
            "status": "auto_verified",
            "official_careers_url": final_url,
            "adapter_type": "workday",
            "adapter_parameters": {"tenant": tenant, "site": path_segments[0]},
            "listing_mode": "search_only",
            "list_endpoint": final_url,
            "pagination": "Workday search behavior requires adapter verification.",
            "external_job_id_field": None,
            "publication_date_field": None,
            "publication_date_basis": "unknown",
            "title_field": None,
            "location_field": None,
            "detail_strategy": "detail_page",
            "confidence": "medium",
            "access_concern": None,
            "notes": "Company careers page redirected to a public Workday tenant.",
        }
    )
    _add_probe_evidence(proposal, probe, "workday_redirect_probe")


def _mark_conflict(proposal: dict[str, Any], probe: dict[str, Any]) -> None:
    proposal["status"] = "conflict"
    proposal["confidence"] = "low"
    proposal["access_concern"] = str(probe.get("detail") or "Public source probe failed.")
    _add_probe_evidence(proposal, probe, "failed_source_probe")


def _add_probe_evidence(
    proposal: dict[str, Any],
    probe: dict[str, Any],
    evidence_type: str,
) -> None:
    final_url = probe.get("final_url")
    requested_url = probe.get("requested_url")
    url = final_url if isinstance(final_url, str) else requested_url
    if not isinstance(url, str):
        return
    evidence = proposal.setdefault("evidence", [])
    if not isinstance(evidence, list):
        raise ValueError("proposal evidence must be an array")
    note_parts = [str(probe.get("detail") or "Public read-only probe.")]
    if probe.get("job_count") is not None:
        note_parts.append(f"observed jobs={probe['job_count']}")
    evidence.append(
        {
            "url": url,
            "evidence_type": evidence_type,
            "note": "; ".join(note_parts),
        }
    )
