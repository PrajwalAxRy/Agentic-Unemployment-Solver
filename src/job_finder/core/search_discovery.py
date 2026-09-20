"""Validate ranked web-search evidence and promote only credible source candidates."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

_EXCLUDED_HOST_SUFFIXES = (
    "ambitionbox.com",
    "arxiv.org",
    "facebook.com",
    "glassdoor.com",
    "indeed.com",
    "instagram.com",
    "linkedin.com",
    "naukri.com",
    "reddit.com",
    "wikipedia.org",
    "youtube.com",
)


@dataclass(frozen=True, slots=True)
class RankedSourceCandidate:
    """One search result scored for a specific canonical company."""

    title: str
    url: str
    score: int


@dataclass(frozen=True, slots=True)
class CompanySearchCandidates:
    """Ranked search results for one canonical company."""

    company_id: str
    company_name: str
    source_rank: int
    priority: str
    candidates: tuple[RankedSourceCandidate, ...]


@dataclass(frozen=True, slots=True)
class SearchCandidateBatch:
    """One timestamped, explicitly unreviewed search-evidence batch."""

    searched_at: str
    selection_status: str
    companies: tuple[CompanySearchCandidates, ...]


@dataclass(frozen=True, slots=True)
class SelectedSource:
    """Credible candidate and inferred adapter configuration pending probes."""

    company_id: str
    official_url: str
    title: str
    score: int
    evidence_batch: str
    adapter_type: str
    adapter_parameters: Mapping[str, str]
    list_endpoint: str
    listing_mode: str


def load_search_candidate_batch(path: Path) -> SearchCandidateBatch:
    """Load and validate unreviewed ranked search evidence."""
    with path.open("r", encoding="utf-8") as stream:
        raw = json.load(stream)
    if not isinstance(raw, dict):
        raise ValueError("search candidate batch must be a JSON object")
    if raw.get("schema_version") != 1:
        raise ValueError("search candidate batch schema_version must be 1")
    companies_raw = raw.get("companies")
    if not isinstance(companies_raw, list):
        raise ValueError("search candidate batch.companies must be an array")
    companies = tuple(
        _company_from_mapping(_mapping(item, f"companies[{index}]"))
        for index, item in enumerate(companies_raw)
    )
    company_ids = [company.company_id for company in companies]
    if len(company_ids) != len(set(company_ids)):
        raise ValueError("search candidate batch contains duplicate company IDs")
    return SearchCandidateBatch(
        searched_at=_string(raw, "searched_at", "batch"),
        selection_status=_string(raw, "selection_status", "batch"),
        companies=companies,
    )


def select_credible_sources(
    batches_in_priority_order: Iterable[tuple[str, SearchCandidateBatch]],
) -> dict[str, SelectedSource]:
    """Select the first credible result per company from most-specific evidence first."""
    selected: dict[str, SelectedSource] = {}
    for batch_name, batch in batches_in_priority_order:
        for company in batch.companies:
            if company.company_id in selected:
                continue
            candidate = next(
                (item for item in company.candidates if _credible_candidate(item)),
                None,
            )
            if candidate is None:
                continue
            adapter, parameters, endpoint, listing_mode = infer_adapter(candidate.url)
            selected[company.company_id] = SelectedSource(
                company_id=company.company_id,
                official_url=candidate.url,
                title=candidate.title,
                score=candidate.score,
                evidence_batch=batch_name,
                adapter_type=adapter,
                adapter_parameters=parameters,
                list_endpoint=endpoint,
                listing_mode=listing_mode,
            )
    return selected


def apply_search_selections(
    proposal_payload: dict[str, object],
    selections: Mapping[str, SelectedSource],
) -> dict[str, object]:
    """Promote selected unresolved companies to disabled, probe-ready proposals."""
    proposals = proposal_payload.get("proposals")
    if not isinstance(proposals, list):
        raise ValueError("proposal payload.proposals must be an array")
    found_ids: set[str] = set()
    for item in proposals:
        if not isinstance(item, dict):
            raise ValueError("proposal must be an object")
        company_id = item.get("company_id")
        if not isinstance(company_id, str):
            raise ValueError("proposal.company_id must be a string")
        selection = selections.get(company_id)
        if selection is None:
            continue
        if item.get("status") != "unresolved":
            raise ValueError(f"search selection would overwrite resolved proposal: {company_id}")
        found_ids.add(company_id)
        item.update(
            {
                "status": "proposed",
                "official_careers_url": selection.official_url,
                "regional_board_url": None,
                "adapter_type": selection.adapter_type,
                "adapter_parameters": dict(selection.adapter_parameters),
                "listing_mode": selection.listing_mode,
                "list_endpoint": selection.list_endpoint,
                "pagination": "Requires adapter verification after H2 source approval.",
                "external_job_id_field": None,
                "publication_date_field": None,
                "publication_date_basis": "unknown",
                "publication_date_verified": False,
                "title_field": None,
                "location_field": None,
                "detail_strategy": "detail_page",
                "confidence": "medium" if selection.score >= 30 else "low",
                "evidence": [
                    {
                        "url": selection.official_url,
                        "evidence_type": "ranked_public_search_result",
                        "note": (
                            f"{selection.evidence_batch}; score={selection.score}; "
                            f"title={selection.title}"
                        ),
                    }
                ],
                "access_concern": None,
                "notes": (
                    "Automated search proposal; requires read-only verification and H2 review."
                ),
            }
        )
    missing = sorted(set(selections) - found_ids)
    if missing:
        raise ValueError(
            "search selections do not match unresolved proposals: " + ", ".join(missing)
        )
    return proposal_payload


def infer_adapter(url: str) -> tuple[str, dict[str, str], str, str]:
    """Infer known public ATS parameters from a candidate URL."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
    if host in {"job-boards.greenhouse.io", "boards.greenhouse.io"} and segments:
        token = segments[0]
        return (
            "greenhouse",
            {"board_token": token},
            f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
            "complete_list",
        )
    if host == "jobs.ashbyhq.com" and segments:
        board = segments[0]
        return (
            "ashby",
            {"board_name": board},
            f"https://api.ashbyhq.com/posting-api/job-board/{board}",
            "complete_list",
        )
    if host == "jobs.lever.co" and segments:
        site = segments[0]
        return (
            "lever",
            {"site": site},
            f"https://api.lever.co/v0/postings/{site}?mode=json",
            "complete_list",
        )
    if host.endswith(".myworkdayjobs.com") and segments:
        tenant = host.split(".", maxsplit=1)[0]
        site_index = 1 if len(segments) > 1 and _looks_like_locale(segments[0]) else 0
        site = segments[site_index]
        return "workday", {"tenant": tenant, "site": site}, url, "search_only"
    if host == "careers.smartrecruiters.com" and segments:
        identifier = segments[0]
        return (
            "smartrecruiters",
            {"company_identifier": identifier},
            url,
            "search_only",
        )
    return "search_only", {"search_url": url}, url, "search_only"


def _credible_candidate(candidate: RankedSourceCandidate) -> bool:
    parsed = urlsplit(candidate.url)
    host = (parsed.hostname or "").lower()
    if host == "careers.linkedin.com":
        return True
    if candidate.score < 15 or parsed.path.lower().endswith(".pdf"):
        return False
    return not any(
        host == suffix or host.endswith(f".{suffix}") for suffix in _EXCLUDED_HOST_SUFFIXES
    )


def _looks_like_locale(value: str) -> bool:
    parts = value.replace("_", "-").split("-")
    return len(parts) == 2 and len(parts[0]) == 2 and len(parts[1]) == 2


def _company_from_mapping(raw: Mapping[str, object]) -> CompanySearchCandidates:
    candidates_raw = raw.get("candidates")
    if not isinstance(candidates_raw, list) or not candidates_raw:
        raise ValueError("company search candidates must be a non-empty array")
    candidates = tuple(
        _candidate_from_mapping(_mapping(item, "candidate")) for item in candidates_raw
    )
    priority = _string(raw, "priority", "company")
    if priority not in {"P1", "P2", "P3"}:
        raise ValueError("company.priority must be one of: P1, P2, P3")
    source_rank_raw = raw.get("source_rank")
    source_rank = (
        int(source_rank_raw)
        if isinstance(source_rank_raw, str) and source_rank_raw.isdigit()
        else source_rank_raw
    )
    if not isinstance(source_rank, int) or isinstance(source_rank, bool) or source_rank <= 0:
        raise ValueError("company.source_rank must be a positive integer")
    return CompanySearchCandidates(
        company_id=_string(raw, "company_id", "company"),
        company_name=_string(raw, "company_name", "company"),
        source_rank=source_rank,
        priority=priority,
        candidates=candidates,
    )


def _candidate_from_mapping(raw: Mapping[str, object]) -> RankedSourceCandidate:
    score = raw.get("score")
    if not isinstance(score, int) or isinstance(score, bool):
        raise ValueError("candidate.score must be an integer")
    url = _string(raw, "url", "candidate")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("candidate.url must be an absolute HTTP or HTTPS URL")
    return RankedSourceCandidate(
        title=_string(raw, "title", "candidate"),
        url=url,
        score=score,
    )


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    return value


def _string(raw: Mapping[str, object], key: str, path: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}.{key} must be a non-empty string")
    return value.strip()
