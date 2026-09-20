"""Guarded application of successful adapter-group validation evidence."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from urllib.parse import quote

ASHBY_DOCUMENTATION_URL = "https://developers.ashbyhq.com/docs/public-job-posting-api"
GREENHOUSE_DOCUMENTATION_URL = "https://docs.greenhouse.io/job-board.html"
LEVER_DOCUMENTATION_URL = "https://github.com/lever/postings-api"


def apply_ashby_validation(
    proposal_payload: dict[str, Any],
    report_payload: dict[str, Any],
) -> dict[str, Any]:
    """Mark every Ashby proposal verified only after a complete healthy group report."""
    revised = deepcopy(proposal_payload)
    proposals = revised.get("proposals")
    records = report_payload.get("records")
    if not isinstance(proposals, list) or not isinstance(records, list):
        raise ValueError("proposal and verification payloads require arrays")
    if report_payload.get("schema_version") != 1:
        raise ValueError("verification report schema_version must be 1")
    if report_payload.get("adapter_type") != "ashby":
        raise ValueError("verification report must target ashby")

    ashby_proposals: dict[str, dict[str, Any]] = {}
    for item in proposals:
        if not isinstance(item, dict) or item.get("adapter_type") != "ashby":
            continue
        company_id = item.get("company_id")
        if not isinstance(company_id, str) or not company_id:
            raise ValueError("Ashby proposal requires company_id")
        ashby_proposals[company_id] = item
    report_by_id: dict[str, dict[str, Any]] = {}
    for raw in records:
        if not isinstance(raw, dict):
            raise ValueError("verification record must be an object")
        raw_company_id = raw.get("company_id")
        if not isinstance(raw_company_id, str) or not raw_company_id:
            raise ValueError("verification record requires company_id")
        record_company_id: str = raw_company_id
        if record_company_id in report_by_id:
            raise ValueError(f"duplicate verification company_id: {record_company_id}")
        if raw.get("adapter_type") != "ashby":
            raise ValueError(f"verification record is not ashby: {record_company_id}")
        if raw.get("outcome") not in {"success", "empty"} or raw.get("complete") is not True:
            raise ValueError(
                f"verification record is not healthy and complete: {record_company_id}"
            )
        report_by_id[record_company_id] = raw
    if set(report_by_id) != set(ashby_proposals):
        missing = sorted(set(ashby_proposals) - set(report_by_id))
        extra = sorted(set(report_by_id) - set(ashby_proposals))
        raise ValueError(f"verification coverage mismatch; missing={missing}; extra={extra}")

    generated_at = report_payload.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        raise ValueError("verification report requires generated_at")
    for company_id, proposal in ashby_proposals.items():
        parameters = proposal.get("adapter_parameters")
        if not isinstance(parameters, dict):
            raise ValueError(f"Ashby proposal requires adapter_parameters: {company_id}")
        board_name = parameters.get("board_name")
        if not isinstance(board_name, str) or not board_name.strip():
            raise ValueError(f"Ashby proposal requires board_name: {company_id}")
        encoded_board = quote(board_name.strip(), safe="")
        record = report_by_id[company_id]
        proposal.update(
            {
                "status": "auto_verified",
                "official_careers_url": f"https://jobs.ashbyhq.com/{encoded_board}",
                "list_endpoint": ("https://api.ashbyhq.com/posting-api/job-board/" + encoded_board),
                "pagination": (
                    "Official public posting API returns one complete jobs collection without "
                    "page tokens; verified in Phase 3."
                ),
                "external_job_id_field": "id",
                "publication_date_field": "publishedAt",
                "publication_date_basis": "published",
                "publication_date_verified": True,
                "title_field": "title",
                "location_field": "location",
                "detail_strategy": "listing_payload",
                "confidence": "high",
                "access_concern": None,
                "notes": "Ashby public job-posting API passed full adapter-group validation.",
            }
        )
        evidence = proposal.setdefault("evidence", [])
        if not isinstance(evidence, list):
            raise ValueError(f"Ashby proposal evidence must be an array: {company_id}")
        _append_unique_evidence(
            evidence,
            {
                "url": ASHBY_DOCUMENTATION_URL,
                "evidence_type": "official_adapter_documentation",
                "note": (
                    "Official field contract confirms complete published postings, publishedAt, "
                    "locations, URLs, and listing-payload descriptions."
                ),
            },
        )
        _append_unique_evidence(
            evidence,
            {
                "url": proposal["list_endpoint"],
                "evidence_type": "full_adapter_group_validation",
                "note": (
                    f"{generated_at}; outcome={record['outcome']}; "
                    f"jobs={record.get('job_count')}; pages={record.get('page_count')}; "
                    f"missing_fields={record.get('missing_field_count')}"
                ),
            },
        )
    return revised


def apply_greenhouse_validation(
    proposal_payload: dict[str, Any],
    report_payload: dict[str, Any],
) -> dict[str, Any]:
    """Mark every Greenhouse proposal verified after one complete healthy group report."""
    revised = deepcopy(proposal_payload)
    proposals = revised.get("proposals")
    records = report_payload.get("records")
    if not isinstance(proposals, list) or not isinstance(records, list):
        raise ValueError("proposal and verification payloads require arrays")
    if report_payload.get("schema_version") != 1:
        raise ValueError("verification report schema_version must be 1")
    if report_payload.get("adapter_type") != "greenhouse":
        raise ValueError("verification report must target greenhouse")

    greenhouse_proposals: dict[str, dict[str, Any]] = {}
    for item in proposals:
        if not isinstance(item, dict) or item.get("adapter_type") != "greenhouse":
            continue
        company_id = item.get("company_id")
        if not isinstance(company_id, str) or not company_id:
            raise ValueError("Greenhouse proposal requires company_id")
        greenhouse_proposals[company_id] = item
    report_by_id: dict[str, dict[str, Any]] = {}
    for raw in records:
        if not isinstance(raw, dict):
            raise ValueError("verification record must be an object")
        company_id = raw.get("company_id")
        if not isinstance(company_id, str) or not company_id:
            raise ValueError("verification record requires company_id")
        if company_id in report_by_id:
            raise ValueError(f"duplicate verification company_id: {company_id}")
        if raw.get("adapter_type") != "greenhouse":
            raise ValueError(f"verification record is not greenhouse: {company_id}")
        if raw.get("outcome") not in {"success", "empty"} or raw.get("complete") is not True:
            raise ValueError(f"verification record is not healthy and complete: {company_id}")
        report_by_id[company_id] = raw
    if set(report_by_id) != set(greenhouse_proposals):
        missing = sorted(set(greenhouse_proposals) - set(report_by_id))
        extra = sorted(set(report_by_id) - set(greenhouse_proposals))
        raise ValueError(f"verification coverage mismatch; missing={missing}; extra={extra}")

    generated_at = report_payload.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        raise ValueError("verification report requires generated_at")
    for company_id, proposal in greenhouse_proposals.items():
        parameters = proposal.get("adapter_parameters")
        if not isinstance(parameters, dict):
            raise ValueError(f"Greenhouse proposal requires adapter_parameters: {company_id}")
        board_token = parameters.get("board_token")
        if not isinstance(board_token, str) or not board_token.strip():
            raise ValueError(f"Greenhouse proposal requires board_token: {company_id}")
        encoded_token = quote(board_token.strip(), safe="")
        record = report_by_id[company_id]
        date_distribution = record.get("date_basis_distribution")
        updated_count = (
            date_distribution.get("updated", 0) if isinstance(date_distribution, dict) else 0
        )
        unknown_count = (
            date_distribution.get("unknown", 0) if isinstance(date_distribution, dict) else 0
        )
        proposal.update(
            {
                "status": "auto_verified",
                "official_careers_url": f"https://job-boards.greenhouse.io/{encoded_token}",
                "list_endpoint": (
                    f"https://boards-api.greenhouse.io/v1/boards/{encoded_token}/jobs?content=true"
                ),
                "pagination": (
                    "Official public Job Board API returns one complete jobs collection with "
                    "meta.total; verified in Phase 4."
                ),
                "external_job_id_field": "id",
                "publication_date_field": "first_published",
                "publication_date_basis": "published",
                "publication_date_verified": True,
                "title_field": "title",
                "location_field": "location.name",
                "detail_strategy": "listing_payload",
                "confidence": "high",
                "access_concern": None,
                "notes": (
                    "Greenhouse public Job Board API passed full adapter-group validation; "
                    "jobs without first_published retain updated_at separately for H5."
                ),
            }
        )
        evidence = proposal.setdefault("evidence", [])
        if not isinstance(evidence, list):
            raise ValueError(f"Greenhouse proposal evidence must be an array: {company_id}")
        _append_unique_evidence(
            evidence,
            {
                "url": GREENHOUSE_DOCUMENTATION_URL,
                "evidence_type": "official_adapter_documentation",
                "note": (
                    "Official Job Board API contract confirms the complete jobs collection, "
                    "job identifiers, first_published, locations, URLs, and content payload."
                ),
            },
        )
        _append_unique_evidence(
            evidence,
            {
                "url": proposal["list_endpoint"],
                "evidence_type": "full_adapter_group_validation",
                "note": (
                    f"{generated_at}; outcome={record['outcome']}; "
                    f"jobs={record.get('job_count')}; pages={record.get('page_count')}; "
                    f"missing_fields={record.get('missing_field_count')}; "
                    f"updated_fallback={updated_count}; unknown_dates={unknown_count}"
                ),
            },
        )
    return revised


def apply_lever_validation(
    proposal_payload: dict[str, Any],
    report_payload: dict[str, Any],
) -> dict[str, Any]:
    """Mark every current Lever proposal verified after a complete healthy group report."""
    revised = deepcopy(proposal_payload)
    proposals = revised.get("proposals")
    records = report_payload.get("records")
    if not isinstance(proposals, list) or not isinstance(records, list):
        raise ValueError("proposal and verification payloads require arrays")
    if report_payload.get("schema_version") != 1:
        raise ValueError("verification report schema_version must be 1")
    if report_payload.get("adapter_type") != "lever":
        raise ValueError("verification report must target lever")

    lever_proposals: dict[str, dict[str, Any]] = {}
    for item in proposals:
        if not isinstance(item, dict) or item.get("adapter_type") != "lever":
            continue
        company_id = item.get("company_id")
        if not isinstance(company_id, str) or not company_id:
            raise ValueError("Lever proposal requires company_id")
        lever_proposals[company_id] = item
    report_by_id: dict[str, dict[str, Any]] = {}
    for raw in records:
        if not isinstance(raw, dict):
            raise ValueError("verification record must be an object")
        company_id = raw.get("company_id")
        if not isinstance(company_id, str) or not company_id:
            raise ValueError("verification record requires company_id")
        if company_id in report_by_id:
            raise ValueError(f"duplicate verification company_id: {company_id}")
        if raw.get("adapter_type") != "lever":
            raise ValueError(f"verification record is not lever: {company_id}")
        if raw.get("outcome") not in {"success", "empty"} or raw.get("complete") is not True:
            raise ValueError(f"verification record is not healthy and complete: {company_id}")
        report_by_id[company_id] = raw
    if set(report_by_id) != set(lever_proposals):
        missing = sorted(set(lever_proposals) - set(report_by_id))
        extra = sorted(set(report_by_id) - set(lever_proposals))
        raise ValueError(f"verification coverage mismatch; missing={missing}; extra={extra}")

    generated_at = report_payload.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        raise ValueError("verification report requires generated_at")
    for company_id, proposal in lever_proposals.items():
        parameters = proposal.get("adapter_parameters")
        if not isinstance(parameters, dict):
            raise ValueError(f"Lever proposal requires adapter_parameters: {company_id}")
        site = parameters.get("site")
        if not isinstance(site, str) or not site.strip():
            raise ValueError(f"Lever proposal requires site: {company_id}")
        encoded_site = quote(site.strip(), safe="")
        record = report_by_id[company_id]
        date_distribution = record.get("date_basis_distribution")
        unknown_count = (
            date_distribution.get("unknown", 0) if isinstance(date_distribution, dict) else 0
        )
        proposal.update(
            {
                "status": "auto_verified",
                "official_careers_url": f"https://jobs.lever.co/{encoded_site}",
                "list_endpoint": (f"https://api.lever.co/v0/postings/{encoded_site}?mode=json"),
                "pagination": (
                    "Official public Postings API uses skip/limit pagination; verified until a "
                    "short page in Phase 4."
                ),
                "external_job_id_field": "id",
                "publication_date_field": "createdAt",
                "publication_date_basis": "unknown",
                "publication_date_verified": False,
                "title_field": "text",
                "location_field": "categories.location",
                "detail_strategy": "listing_payload",
                "confidence": "high",
                "access_concern": None,
                "notes": (
                    "Lever public Postings API passed full adapter-group validation. createdAt "
                    "remains uncertain date evidence for H5; missing descriptions stay explicit."
                ),
            }
        )
        evidence = proposal.setdefault("evidence", [])
        if not isinstance(evidence, list):
            raise ValueError(f"Lever proposal evidence must be an array: {company_id}")
        _append_unique_evidence(
            evidence,
            {
                "url": LEVER_DOCUMENTATION_URL,
                "evidence_type": "official_adapter_documentation",
                "note": (
                    "Official Postings API contract confirms public published jobs, stable IDs, "
                    "skip/limit pagination, locations, URLs, and description fields."
                ),
            },
        )
        _append_unique_evidence(
            evidence,
            {
                "url": proposal["list_endpoint"],
                "evidence_type": "full_adapter_group_validation",
                "note": (
                    f"{generated_at}; outcome={record['outcome']}; "
                    f"jobs={record.get('job_count')}; pages={record.get('page_count')}; "
                    f"missing_fields={record.get('missing_field_count')}; "
                    f"unknown_dates={unknown_count}"
                ),
            },
        )
    return revised


def apply_workday_validation(
    proposal_payload: dict[str, Any],
    report_payload: dict[str, Any],
) -> dict[str, Any]:
    """Mark every Workday proposal verified after a complete healthy group report."""
    revised = deepcopy(proposal_payload)
    proposals = revised.get("proposals")
    records = report_payload.get("records")
    if not isinstance(proposals, list) or not isinstance(records, list):
        raise ValueError("proposal and verification payloads require arrays")
    if report_payload.get("schema_version") != 1:
        raise ValueError("verification report schema_version must be 1")
    if report_payload.get("adapter_type") != "workday":
        raise ValueError("verification report must target workday")

    workday_proposals: dict[str, dict[str, Any]] = {}
    for item in proposals:
        if not isinstance(item, dict) or item.get("adapter_type") != "workday":
            continue
        company_id = item.get("company_id")
        if not isinstance(company_id, str) or not company_id:
            raise ValueError("Workday proposal requires company_id")
        workday_proposals[company_id] = item
    report_by_id: dict[str, dict[str, Any]] = {}
    for raw in records:
        if not isinstance(raw, dict):
            raise ValueError("verification record must be an object")
        company_id = raw.get("company_id")
        if not isinstance(company_id, str) or not company_id:
            raise ValueError("verification record requires company_id")
        if company_id in report_by_id:
            raise ValueError(f"duplicate verification company_id: {company_id}")
        if raw.get("adapter_type") != "workday":
            raise ValueError(f"verification record is not workday: {company_id}")
        if raw.get("outcome") not in {"success", "empty"} or raw.get("complete") is not True:
            raise ValueError(f"verification record is not healthy and complete: {company_id}")
        report_by_id[company_id] = raw
    if set(report_by_id) != set(workday_proposals):
        missing = sorted(set(workday_proposals) - set(report_by_id))
        extra = sorted(set(report_by_id) - set(workday_proposals))
        raise ValueError(f"verification coverage mismatch; missing={missing}; extra={extra}")

    generated_at = report_payload.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        raise ValueError("verification report requires generated_at")
    for company_id, proposal in workday_proposals.items():
        parameters = proposal.get("adapter_parameters")
        if not isinstance(parameters, dict):
            raise ValueError(f"Workday proposal requires adapter_parameters: {company_id}")
        host = parameters.get("host")
        tenant = parameters.get("tenant")
        site = parameters.get("site")
        if not all(isinstance(value, str) and value.strip() for value in (host, tenant, site)):
            raise ValueError(f"Workday proposal requires host, tenant, and site: {company_id}")
        encoded_tenant = quote(str(tenant).strip(), safe="")
        encoded_site = quote(str(site).strip(), safe="")
        board_url = f"https://{str(host).strip().lower()}/{encoded_site}"
        endpoint = (
            f"https://{str(host).strip().lower()}/wday/cxs/{encoded_tenant}/{encoded_site}/jobs"
        )
        record = report_by_id[company_id]
        date_distribution = record.get("date_basis_distribution")
        unknown_count = (
            date_distribution.get("unknown", 0) if isinstance(date_distribution, dict) else 0
        )
        proposal.update(
            {
                "status": "auto_verified",
                "official_careers_url": board_url,
                "list_endpoint": endpoint,
                "pagination": (
                    "Public Candidate Experience API uses offset/limit pagination; the first "
                    "page total is authoritative because later pages report zero."
                ),
                "external_job_id_field": "bulletFields[0]",
                "publication_date_field": "postedOn",
                "publication_date_basis": "unknown",
                "publication_date_verified": False,
                "title_field": "title",
                "location_field": "locationsText",
                "detail_strategy": "detail_endpoint",
                "confidence": "high",
                "access_concern": None,
                "notes": (
                    "Workday public Candidate Experience endpoints passed full adapter-group "
                    "validation. Relative postedOn labels remain uncertain for H5; missing or "
                    "multi-location summaries are checked against the public detail endpoint, "
                    "and genuinely absent locations remain explicit."
                ),
            }
        )
        evidence = proposal.setdefault("evidence", [])
        if not isinstance(evidence, list):
            raise ValueError(f"Workday proposal evidence must be an array: {company_id}")
        _append_unique_evidence(
            evidence,
            {
                "url": endpoint,
                "evidence_type": "full_adapter_group_validation",
                "note": (
                    f"{generated_at}; outcome={record['outcome']}; "
                    f"jobs={record.get('job_count')}; pages={record.get('page_count')}; "
                    f"missing_fields={record.get('missing_field_count')}; "
                    f"unknown_dates={unknown_count}"
                ),
            },
        )
    return revised


def apply_darwinbox_validation(
    proposal_payload: dict[str, Any],
    report_payload: dict[str, Any],
) -> dict[str, Any]:
    """Mark every Darwinbox proposal verified after a complete healthy group report."""
    revised = deepcopy(proposal_payload)
    proposals = revised.get("proposals")
    records = report_payload.get("records")
    if not isinstance(proposals, list) or not isinstance(records, list):
        raise ValueError("proposal and verification payloads require arrays")
    if report_payload.get("schema_version") != 1:
        raise ValueError("verification report schema_version must be 1")
    if report_payload.get("adapter_type") != "darwinbox":
        raise ValueError("verification report must target darwinbox")

    darwinbox_proposals: dict[str, dict[str, Any]] = {}
    for item in proposals:
        if not isinstance(item, dict) or item.get("adapter_type") != "darwinbox":
            continue
        company_id = item.get("company_id")
        if not isinstance(company_id, str) or not company_id:
            raise ValueError("Darwinbox proposal requires company_id")
        darwinbox_proposals[company_id] = item
    report_by_id: dict[str, dict[str, Any]] = {}
    for raw in records:
        if not isinstance(raw, dict):
            raise ValueError("verification record must be an object")
        company_id = raw.get("company_id")
        if not isinstance(company_id, str) or not company_id:
            raise ValueError("verification record requires company_id")
        if company_id in report_by_id:
            raise ValueError(f"duplicate verification company_id: {company_id}")
        if raw.get("adapter_type") != "darwinbox":
            raise ValueError(f"verification record is not darwinbox: {company_id}")
        if raw.get("outcome") not in {"success", "empty"} or raw.get("complete") is not True:
            raise ValueError(f"verification record is not healthy and complete: {company_id}")
        report_by_id[company_id] = raw
    if set(report_by_id) != set(darwinbox_proposals):
        missing = sorted(set(darwinbox_proposals) - set(report_by_id))
        extra = sorted(set(report_by_id) - set(darwinbox_proposals))
        raise ValueError(f"verification coverage mismatch; missing={missing}; extra={extra}")

    generated_at = report_payload.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        raise ValueError("verification report requires generated_at")
    for company_id, proposal in darwinbox_proposals.items():
        parameters = proposal.get("adapter_parameters")
        if not isinstance(parameters, dict):
            raise ValueError(f"Darwinbox proposal requires adapter_parameters: {company_id}")
        tenant = parameters.get("tenant")
        if not isinstance(tenant, str) or not tenant.strip():
            raise ValueError(f"Darwinbox proposal requires tenant: {company_id}")
        encoded_tenant = tenant.strip().lower()
        board_url = f"https://{encoded_tenant}.darwinbox.in/ms/candidate/careers"
        endpoint = f"https://{encoded_tenant}.darwinbox.in/ms/candidateapi/job?page=1"
        record = report_by_id[company_id]
        date_distribution = record.get("date_basis_distribution")
        unknown_count = (
            date_distribution.get("unknown", 0) if isinstance(date_distribution, dict) else 0
        )
        proposal.update(
            {
                "status": "auto_verified",
                "official_careers_url": board_url,
                "list_endpoint": endpoint,
                "pagination": (
                    "Public candidate API returns ten jobs per numbered page with jobscount; "
                    "verified through the reported total."
                ),
                "external_job_id_field": "id",
                "publication_date_field": "job_posting_on",
                "publication_date_basis": "unknown",
                "publication_date_verified": False,
                "title_field": "title",
                "location_field": "officelocation_show_arr",
                "detail_strategy": "detail_endpoint",
                "confidence": "high",
                "access_concern": None,
                "notes": (
                    "Darwinbox public candidate endpoints passed full adapter-group validation. "
                    "Requests use a same-origin public careers-page referer without cookies or "
                    "authentication; job_posting_on remains uncertain for H5."
                ),
            }
        )
        evidence = proposal.setdefault("evidence", [])
        if not isinstance(evidence, list):
            raise ValueError(f"Darwinbox proposal evidence must be an array: {company_id}")
        _append_unique_evidence(
            evidence,
            {
                "url": endpoint,
                "evidence_type": "full_adapter_group_validation",
                "note": (
                    f"{generated_at}; outcome={record['outcome']}; "
                    f"jobs={record.get('job_count')}; pages={record.get('page_count')}; "
                    f"missing_fields={record.get('missing_field_count')}; "
                    f"unknown_dates={unknown_count}"
                ),
            },
        )
    return revised


def _append_unique_evidence(evidence: list[object], item: dict[str, str]) -> None:
    if item not in evidence:
        evidence.append(item)
