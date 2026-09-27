"""Full-seed assertions for the tracked company source registry."""

from pathlib import Path

from job_finder.core.company_registry import audit_company_registry, load_company_registry
from job_finder.core.company_seed import load_company_seed


def test_canonical_registry_accounts_for_all_companies_and_enables_supported_sources() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    audit = audit_company_registry(registry, load_company_seed(Path("data/company_seed.csv")))

    assert audit.reconciled is True
    assert audit.registry_total == 330
    assert audit.enabled_count == 86
    assert audit.by_status == {"enabled": 86, "proposed": 242, "unsupported": 2}
    assert audit.by_adapter == {
        "ashby": 25,
        "custom": 1,
        "darwinbox": 4,
        "eightfold": 1,
        "greenhouse": 24,
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
    assert all(source.status.value == "enabled" for source in oracle_sources.values())
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
    assert all(source.enabled is True for source in oracle_sources.values())


def test_successfactors_mapping_and_moodys_correction_are_explicit() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    sources = {entry.source.company_id: entry.source for entry in registry.entries}
    sap = sources["sap"]
    moodys = sources["moody-s"]

    assert sap.adapter_type.value == "successfactors"
    assert sap.careers_url == "https://careers.sap.com/go/SAP-Jobs-in-India/851201/"
    assert sap.adapter_parameters == {
        "host": "careers.sap.com",
        "category_path": "/go/SAP-Jobs-in-India/851201/",
    }
    assert sap.status.value == "enabled"
    assert sap.identity_strategy.value == "external_id"
    assert sap.date_strategy.field_name == "datePosted"
    assert sap.date_strategy.basis.value == "published"
    assert sap.date_strategy.verified_as_publication is True
    assert sap.enabled is True

    assert moodys.adapter_type.value == "search_only"
    assert moodys.adapter_parameters == {"search_url": "https://careers.moodys.com/en/search-jobs"}
    assert moodys.exception_reason is not None
    assert "returning-applicant login" in moodys.exception_reason


def test_jobvite_source_uses_verified_board_identity_and_detail_date() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    sima = next(entry.source for entry in registry.entries if entry.source.company_id == "sima-ai")

    assert sima.adapter_type.value == "jobvite"
    assert sima.adapter_parameters == {"company": "simaai"}
    assert sima.status.value == "enabled"
    assert sima.identity_strategy.value == "external_id"
    assert sima.date_strategy.field_name == "datePosted"
    assert sima.date_strategy.basis.value == "published"
    assert sima.date_strategy.verified_as_publication is True
    assert sima.detail_strategy.value == "detail_page"
    assert sima.enabled is True


def test_atomicwork_uses_approved_webflow_adapter_and_unknown_dates() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    atomicwork = next(
        entry.source for entry in registry.entries if entry.source.company_id == "atomicwork"
    )

    assert atomicwork.adapter_type.value == "custom"
    assert atomicwork.careers_url == "https://www.atomicwork.com/company/careers"
    assert atomicwork.adapter_parameters == {"adapter_key": "atomicwork_webflow"}
    assert atomicwork.status.value == "enabled"
    assert atomicwork.identity_strategy.value == "external_id"
    assert atomicwork.date_strategy.field_name is None
    assert atomicwork.date_strategy.basis.value == "unknown"
    assert atomicwork.date_strategy.verified_as_publication is False
    assert atomicwork.detail_strategy.value == "detail_page"
    assert atomicwork.enabled is True
