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
    assert audit.by_status == {"proposed": 50, "unresolved": 280}
    assert audit.by_adapter == {
        "ashby": 19,
        "greenhouse": 9,
        "lever": 5,
        "search_only": 14,
        "unresolved": 282,
        "workday": 1,
    }
