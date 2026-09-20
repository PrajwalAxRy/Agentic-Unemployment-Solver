"""Tests for search-evidence selection and ATS inference."""

from __future__ import annotations

import json
from pathlib import Path

from job_finder.core.search_discovery import (
    CompanySearchCandidates,
    RankedSourceCandidate,
    SearchCandidateBatch,
    apply_search_selections,
    infer_adapter,
    load_search_candidate_batch,
    select_credible_sources,
)


def batch(*candidates: RankedSourceCandidate) -> SearchCandidateBatch:
    return SearchCandidateBatch(
        searched_at="2026-09-20T00:00:00+05:30",
        selection_status="unreviewed",
        companies=(
            CompanySearchCandidates(
                company_id="example",
                company_name="Example",
                source_rank=1,
                priority="P1",
                candidates=candidates,
            ),
        ),
    )


def candidate(url: str, score: int = 30) -> RankedSourceCandidate:
    return RankedSourceCandidate(title="Example Careers", url=url, score=score)


def test_weak_and_aggregator_candidates_remain_unselected() -> None:
    sources = select_credible_sources(
        [
            (
                "test",
                batch(
                    candidate("https://www.linkedin.com/company/example/jobs", 50),
                    candidate("https://example.com/careers", 10),
                ),
            )
        ]
    )

    assert sources == {}


def test_official_linkedin_careers_subdomain_is_allowed() -> None:
    sources = select_credible_sources(
        [("test", batch(candidate("https://careers.linkedin.com/", -3)))]
    )

    assert sources["example"].official_url == "https://careers.linkedin.com/"


def test_more_specific_batch_wins() -> None:
    selected = select_credible_sources(
        [
            ("isolated", batch(candidate("https://example.com/careers", 30))),
            ("initial", batch(candidate("https://jobs.example.com", 50))),
        ]
    )

    assert selected["example"].evidence_batch == "isolated"


def test_known_ats_urls_produce_required_parameters_and_endpoint() -> None:
    adapter, parameters, endpoint, mode = infer_adapter(
        "https://job-boards.greenhouse.io/example/jobs/123"
    )

    assert adapter == "greenhouse"
    assert parameters == {"board_token": "example"}
    assert endpoint.endswith("/boards/example/jobs?content=true")
    assert mode == "complete_list"


def test_workday_job_url_skips_locale_to_find_site() -> None:
    adapter, parameters, _, _ = infer_adapter(
        "https://example.wd1.myworkdayjobs.com/en-US/External/job/India/Role_R1"
    )

    assert adapter == "workday"
    assert parameters == {
        "host": "example.wd1.myworkdayjobs.com",
        "tenant": "example",
        "site": "External",
    }


def test_selection_only_updates_unresolved_proposal() -> None:
    selection = select_credible_sources(
        [("test", batch(candidate("https://jobs.lever.co/example", 35)))]
    )
    payload: dict[str, object] = {
        "proposals": [
            {
                "company_id": "example",
                "status": "unresolved",
                "evidence": [],
            }
        ]
    }

    revised = apply_search_selections(payload, selection)
    proposal = revised["proposals"]
    assert isinstance(proposal, list)
    assert proposal[0]["status"] == "proposed"
    assert proposal[0]["adapter_type"] == "lever"


def test_search_loader_normalizes_numeric_string_rank(tmp_path: Path) -> None:
    path = tmp_path / "search.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "searched_at": "2026-09-20T00:00:00+05:30",
                "selection_status": "unreviewed",
                "companies": [
                    {
                        "company_id": "example",
                        "company_name": "Example",
                        "source_rank": "1",
                        "priority": "P1",
                        "candidates": [
                            {
                                "title": "Example Careers",
                                "url": "https://example.com/careers",
                                "score": 30,
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_search_candidate_batch(path)

    assert loaded.companies[0].source_rank == 1
