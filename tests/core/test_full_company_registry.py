"""Full-seed assertions for the tracked company source registry."""

from pathlib import Path

from job_finder.core.company_registry import audit_company_registry, load_company_registry
from job_finder.core.company_seed import load_company_seed


def test_canonical_registry_accounts_for_all_companies_and_enables_supported_sources() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    audit = audit_company_registry(registry, load_company_seed(Path("data/company_seed.csv")))

    assert audit.reconciled is True
    assert audit.registry_total == 330
    assert audit.enabled_count == 107
    assert audit.by_status == {"enabled": 107, "proposed": 221, "unsupported": 2}
    assert audit.by_adapter == {
        "ashby": 26,
        "custom": 1,
        "darwinbox": 4,
        "eightfold": 1,
        "greenhouse": 33,
        "jobvite": 1,
        "lever": 12,
        "oracle_cloud": 3,
        "search_only": 217,
        "smartrecruiters": 4,
        "successfactors": 1,
        "unsupported": 2,
        "unresolved": 4,
        "workday": 21,
    }


def test_phase12_package_a_activates_only_live_validated_existing_adapters() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    sources = {entry.source.company_id: entry.source for entry in registry.entries}
    expected = {
        "rubrik": ("greenhouse", {"board_token": "rubrik"}),
        "cockroach-labs": ("greenhouse", {"board_token": "cockroachlabs"}),
        "falconx": ("greenhouse", {"board_token": "falconx"}),
        "okta": ("greenhouse", {"board_token": "okta"}),
        "nk-securities": ("greenhouse", {"board_token": "nksecuritiesresearch"}),
        "aqr-capital-management": ("greenhouse", {"board_token": "india"}),
        "coinbase": ("greenhouse", {"board_token": "coinbase"}),
        "compass": ("greenhouse", {"board_token": "compassindia"}),
        "crunchyroll": ("greenhouse", {"board_token": "crunchyroll"}),
        "cred": ("lever", {"site": "cred"}),
        "testgorilla": ("ashby", {"board_name": "testgorilla"}),
        "slack": (
            "workday",
            {"host": "salesforce.wd12.myworkdayjobs.com", "tenant": "salesforce", "site": "Slack"},
        ),
        "broadcom": (
            "workday",
            {
                "host": "broadcom.wd1.myworkdayjobs.com",
                "tenant": "broadcom",
                "site": "External_Career",
            },
        ),
        "quantiphi": (
            "workday",
            {
                "host": "quantiphi.wd1.myworkdayjobs.com",
                "tenant": "quantiphi",
                "site": "Careers_at_Quantiphi",
            },
        ),
        "mastercard": (
            "workday",
            {
                "host": "mastercard.wd1.myworkdayjobs.com",
                "tenant": "mastercard",
                "site": "CorporateCareers",
            },
        ),
        "kla": (
            "workday",
            {"host": "kla.wd1.myworkdayjobs.com", "tenant": "kla", "site": "Search"},
        ),
        "marvell": (
            "workday",
            {
                "host": "marvell.wd1.myworkdayjobs.com",
                "tenant": "marvell",
                "site": "MarvellCareers",
            },
        ),
        "aptiv": (
            "workday",
            {"host": "aptiv.wd5.myworkdayjobs.com", "tenant": "aptiv", "site": "APTIV_CAREERS"},
        ),
        "browserstack": (
            "workday",
            {
                "host": "browserstack.wd3.myworkdayjobs.com",
                "tenant": "browserstack",
                "site": "External",
            },
        ),
        "texas-instruments": (
            "oracle_cloud",
            {"host": "edbz.fa.us2.oraclecloud.com", "site_number": "CX"},
        ),
        "renesas": ("smartrecruiters", {"company_identifier": "RenesasElectronics"}),
    }

    assert registry.registry_version == "0.3.0-phase12-a1"
    for company_id, (adapter_type, parameters) in expected.items():
        source = sources[company_id]
        assert source.enabled is True
        assert source.status.value == "enabled"
        assert source.adapter_type.value == adapter_type
        assert source.adapter_parameters == parameters

    for company_id in (
        "salesforce",
        "qualcomm",
        "navan",
        "opendoor",
        "thoughtspot",
        "eightfold-ai",
        "morgan-stanley",
        "games24x7",
    ):
        assert sources[company_id].enabled is False
        assert sources[company_id].adapter_type.value == "search_only"


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
