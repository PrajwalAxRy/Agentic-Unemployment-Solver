"""Tests for deterministic proposal generation from seed URL hints."""

from pathlib import Path

from job_finder.core.company_seed import CompanySeedRecord, load_company_seed
from job_finder.core.discovery_baseline import build_baseline_proposal
from job_finder.core.source_discovery import audit_discovery_batch, load_discovery_batch


def record(url: str) -> CompanySeedRecord:
    return CompanySeedRecord(
        company_id="example",
        company_name="Example",
        priority="P1",
        careers_url_hint=url,
        source_rank=1,
    )


def test_greenhouse_hint_extracts_board_token_without_approving_it() -> None:
    proposal = build_baseline_proposal(
        record("https://job-boards.greenhouse.io/exampleboard/jobs/123")
    )

    assert proposal["status"] == "proposed"
    assert proposal["adapter_type"] == "greenhouse"
    assert proposal["adapter_parameters"] == {"board_token": "exampleboard"}


def test_ashby_and_lever_hints_extract_board_parameters() -> None:
    ashby = build_baseline_proposal(record("https://jobs.ashbyhq.com/Example%20AI/job-id"))
    lever = build_baseline_proposal(record("https://jobs.lever.co/example?location=India"))

    assert ashby["adapter_parameters"] == {"board_name": "Example AI"}
    assert lever["adapter_parameters"] == {"site": "example"}


def test_google_hint_remains_explicitly_unresolved() -> None:
    proposal = build_baseline_proposal(
        record("https://www.google.com/search?q=Example%20careers%20India")
    )

    assert proposal["status"] == "unresolved"
    assert proposal["official_careers_url"] is None
    assert proposal["confidence"] == "unknown"


def test_third_party_hint_is_a_conflict_not_an_official_source() -> None:
    proposal = build_baseline_proposal(record("https://wellfound.com/company/example/jobs"))

    assert proposal["status"] == "conflict"
    assert proposal["official_careers_url"] is None
    assert proposal["access_concern"] is not None


def test_canonical_discovery_proposals_reconcile_all_companies() -> None:
    seed = load_company_seed(Path("data/company_seed.csv"))
    batch = load_discovery_batch(Path("data/source_discovery_proposals.json"))
    audit = audit_discovery_batch(batch, seed)

    assert audit.reconciled is True
    assert audit.proposal_total == 330
    assert audit.by_status == {
        "auto_verified": 260,
        "conflict": 68,
        "proposed": 2,
    }
    assert audit.by_adapter == {
        "ashby": 24,
        "darwinbox": 4,
        "eightfold": 3,
        "greenhouse": 26,
        "jobvite": 1,
        "lever": 12,
        "oracle_cloud": 2,
        "search_only": 236,
        "smartrecruiters": 3,
        "successfactors": 2,
        "unresolved": 4,
        "workday": 13,
    }
