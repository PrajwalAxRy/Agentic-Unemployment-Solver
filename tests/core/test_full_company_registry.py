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
    assert audit.by_status == {"proposed": 323, "reviewed": 5, "unsupported": 2}
    assert audit.by_adapter == {
        "ashby": 25,
        "darwinbox": 4,
        "eightfold": 1,
        "greenhouse": 25,
        "jobvite": 1,
        "lever": 11,
        "oracle_cloud": 2,
        "search_only": 238,
        "smartrecruiters": 3,
        "successfactors": 1,
        "unsupported": 2,
        "unresolved": 4,
        "workday": 13,
    }


def test_cerebras_uses_case_sensitive_verified_ashby_board_name() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    cerebras = next(
        entry.source for entry in registry.entries if entry.source.company_id == "cerebras-systems"
    )

    assert cerebras.adapter_parameters["board_name"] == "Cerebras"


def test_wisdom_ai_uses_current_verified_ashby_board_name() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    wisdom_ai = next(
        entry.source for entry in registry.entries if entry.source.company_id == "wisdomai"
    )

    assert wisdom_ai.adapter_parameters["board_name"] == "Wisdom-AI"


def test_oracle_cloud_sources_use_verified_public_hosts_and_date_strategy() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    oracle_sources = {
        entry.source.company_id: entry.source
        for entry in registry.entries
        if entry.source.adapter_type.value == "oracle_cloud"
    }

    assert oracle_sources["uber"].adapter_parameters == {
        "host": "iaziqy.fa.ocs.oraclecloud.com",
        "site_number": "UberCareers",
    }
    assert oracle_sources["jpmorganchase"].adapter_parameters == {
        "host": "jpmc.fa.oraclecloud.com",
        "site_number": "CX_1001",
    }
    assert all(source.status.value == "reviewed" for source in oracle_sources.values())
    assert all(
        source.identity_strategy.value == "external_id" for source in oracle_sources.values()
    )
    assert all(
        source.date_strategy.field_name == "PostedDate" for source in oracle_sources.values()
    )
    assert all(
        source.date_strategy.basis.value == "published" for source in oracle_sources.values()
    )
    assert all(source.date_strategy.verified_as_publication for source in oracle_sources.values())
    assert all(source.enabled is False for source in oracle_sources.values())
