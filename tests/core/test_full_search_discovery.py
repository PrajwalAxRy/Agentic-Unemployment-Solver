"""Full-batch checks for tracked Phase 2 web-search discovery evidence."""

from pathlib import Path

from job_finder.core.search_discovery import (
    load_search_candidate_batch,
    select_credible_sources,
)
from job_finder.core.source_quality import load_quality_corrections


def test_search_evidence_accounts_for_every_search_hint() -> None:
    root = Path("data")
    batches = [
        (
            "targeted search",
            load_search_candidate_batch(root / "source_search_targeted_candidates.json"),
        ),
        (
            "isolated retry",
            load_search_candidate_batch(root / "source_search_isolated_retries.json"),
        ),
        ("batch retry", load_search_candidate_batch(root / "source_search_retries.json")),
        ("initial search", load_search_candidate_batch(root / "source_search_candidates.json")),
    ]
    initial_ids = {company.company_id for company in batches[-1][1].companies}
    selected = select_credible_sources(batches)

    assert len(initial_ids) == 280
    assert len(selected) == 278
    assert initial_ids - set(selected) == {"info-edge", "ragaai"}


def test_quality_corrections_account_for_every_isolated_retry() -> None:
    quality = load_search_candidate_batch(Path("data/source_search_quality_retries.json"))
    corrections = load_quality_corrections(Path("data/source_quality_corrections.json"))
    replacements = corrections["replacements"]
    downgrades = corrections["downgrades"]
    assert isinstance(replacements, list)
    assert isinstance(downgrades, list)
    correction_ids = {
        item["company_id"] for item in replacements + downgrades if isinstance(item, dict)
    }

    assert len(quality.companies) == 65
    assert correction_ids == {company.company_id for company in quality.companies}
