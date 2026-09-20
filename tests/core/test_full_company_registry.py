"""Full-seed assertions for the tracked provisional company registry."""

from pathlib import Path

from job_finder.core.company_registry import audit_company_registry, load_company_registry
from job_finder.core.company_seed import load_company_seed


def test_canonical_registry_accounts_for_all_companies_and_stays_disabled() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    audit = audit_company_registry(registry, load_company_seed(Path("data/company_seed.csv")))

    assert audit.reconciled is True
    assert audit.registry_total == 330
    assert audit.enabled_count == 0
    assert audit.by_status == {"proposed": 330}
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
