"""Deterministic Phase 2 baseline proposals derived from canonical URL hints."""

from __future__ import annotations

from urllib.parse import quote, unquote, urlsplit, urlunsplit

from job_finder.core.company_seed import CompanySeedRecord


def build_baseline_proposal(record: CompanySeedRecord) -> dict[str, object]:
    """Build a provisional proposal without treating a seed URL hint as approval."""
    parsed = urlsplit(record.careers_url_hint)
    host = (parsed.hostname or "").lower()
    common = {
        "schema_version": 1,
        "company_id": record.company_id,
        "company_name": record.company_name,
        "source_rank": record.source_rank,
        "priority": record.priority,
        "regional_board_url": None,
        "publication_date_verified": False,
        "access_concern": None,
        "notes": "Generated from an unverified canonical seed URL hint; H2 review is required.",
    }

    if host == "www.google.com":
        return {
            **common,
            "status": "unresolved",
            "official_careers_url": None,
            "adapter_type": "unresolved",
            "adapter_parameters": {},
            "listing_mode": "unknown",
            "list_endpoint": None,
            "pagination": "unknown",
            "external_job_id_field": None,
            "publication_date_field": None,
            "publication_date_basis": "unknown",
            "title_field": None,
            "location_field": None,
            "detail_strategy": "unresolved",
            "confidence": "unknown",
            "evidence": [_evidence(record.careers_url_hint, "seed_search_hint")],
        }

    if host == "wellfound.com":
        return {
            **common,
            "status": "conflict",
            "official_careers_url": None,
            "adapter_type": "unresolved",
            "adapter_parameters": {},
            "listing_mode": "unknown",
            "list_endpoint": None,
            "pagination": "unknown",
            "external_job_id_field": None,
            "publication_date_field": None,
            "publication_date_basis": "unknown",
            "title_field": None,
            "location_field": None,
            "detail_strategy": "unresolved",
            "confidence": "low",
            "evidence": [_evidence(record.careers_url_hint, "third_party_hint")],
            "access_concern": (
                "Seed hint is a third-party listing; official source is not verified."
            ),
        }

    if host == "job-boards.greenhouse.io":
        board_token = _first_path_segment(parsed.path)
        board_url = f"https://job-boards.greenhouse.io/{quote(board_token)}"
        return {
            **common,
            "status": "proposed",
            "official_careers_url": board_url,
            "adapter_type": "greenhouse",
            "adapter_parameters": {"board_token": board_token},
            "listing_mode": "complete_list",
            "list_endpoint": f"https://boards-api.greenhouse.io/v1/boards/{quote(board_token)}/jobs",
            "pagination": "public board API; completeness requires live verification",
            "external_job_id_field": "id",
            "publication_date_field": "updated_at",
            "publication_date_basis": "updated",
            "title_field": "title",
            "location_field": "location.name",
            "detail_strategy": "listing_payload",
            "confidence": "high",
            "evidence": [_evidence(record.careers_url_hint, "ats_seed_hint")],
        }

    if host == "jobs.ashbyhq.com":
        board_name = unquote(_first_path_segment(parsed.path))
        encoded_board = quote(board_name, safe="")
        board_url = f"https://jobs.ashbyhq.com/{encoded_board}"
        return {
            **common,
            "status": "proposed",
            "official_careers_url": board_url,
            "adapter_type": "ashby",
            "adapter_parameters": {"board_name": board_name},
            "listing_mode": "complete_list",
            "list_endpoint": f"https://api.ashbyhq.com/posting-api/job-board/{encoded_board}",
            "pagination": "public posting API; completeness requires live verification",
            "external_job_id_field": "id",
            "publication_date_field": "publishedAt",
            "publication_date_basis": "unknown",
            "title_field": "title",
            "location_field": "location",
            "detail_strategy": "listing_payload",
            "confidence": "high",
            "evidence": [_evidence(record.careers_url_hint, "ats_seed_hint")],
        }

    if host == "jobs.lever.co":
        site = _first_path_segment(parsed.path)
        board_url = f"https://jobs.lever.co/{quote(site)}"
        return {
            **common,
            "status": "proposed",
            "official_careers_url": board_url,
            "adapter_type": "lever",
            "adapter_parameters": {"site": site},
            "listing_mode": "complete_list",
            "list_endpoint": f"https://api.lever.co/v0/postings/{quote(site)}?mode=json",
            "pagination": "public postings API; completeness requires live verification",
            "external_job_id_field": "id",
            "publication_date_field": "createdAt",
            "publication_date_basis": "unknown",
            "title_field": "text",
            "location_field": "categories.location",
            "detail_strategy": "listing_payload",
            "confidence": "high",
            "evidence": [_evidence(record.careers_url_hint, "ats_seed_hint")],
        }

    careers_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    return {
        **common,
        "status": "proposed",
        "official_careers_url": careers_url,
        "adapter_type": "search_only",
        "adapter_parameters": {"search_url": careers_url},
        "listing_mode": "search_only",
        "list_endpoint": careers_url,
        "pagination": "unknown; requires live verification",
        "external_job_id_field": None,
        "publication_date_field": None,
        "publication_date_basis": "unknown",
        "title_field": None,
        "location_field": None,
        "detail_strategy": "detail_page",
        "confidence": "medium",
        "evidence": [_evidence(record.careers_url_hint, "company_domain_seed_hint")],
    }


def _first_path_segment(path: str) -> str:
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        raise ValueError("ATS URL hint must contain a board identifier")
    return segments[0]


def _evidence(url: str, evidence_type: str) -> dict[str, object]:
    return {
        "url": url,
        "evidence_type": evidence_type,
        "note": "Canonical seed hint retained as discovery evidence; not yet an approved source.",
    }
