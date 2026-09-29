"""Full-seed assertions for the tracked company source registry."""

from pathlib import Path

from job_finder.core.company_registry import audit_company_registry, load_company_registry
from job_finder.core.company_seed import load_company_seed


def test_canonical_registry_accounts_for_all_companies_and_enables_supported_sources() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    audit = audit_company_registry(registry, load_company_seed(Path("data/company_seed.csv")))

    assert audit.reconciled is True
    assert audit.registry_total == 330
    assert audit.enabled_count == 148
    assert audit.by_status == {"enabled": 148, "proposed": 180, "unsupported": 2}
    assert audit.by_adapter == {
        "ashby": 27,
        "custom": 22,
        "darwinbox": 4,
        "eightfold": 1,
        "freshteam": 2,
        "greenhouse": 39,
        "jobvite": 1,
        "lever": 13,
        "oracle_cloud": 4,
        "recruiterflow": 1,
        "rippling": 1,
        "search_only": 176,
        "sensehq": 1,
        "smartrecruiters": 5,
        "successfactors": 2,
        "unsupported": 2,
        "unresolved": 4,
        "workday": 25,
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

    assert registry.registry_version == "0.3.0-phase12-c19"
    for company_id, (adapter_type, parameters) in expected.items():
        source = sources[company_id]
        assert source.enabled is True
        assert source.status.value == "enabled"
        assert source.adapter_type.value == adapter_type
        assert source.adapter_parameters == parameters

    for company_id in (
        "qualcomm",
        "navan",
        "opendoor",
        "thoughtspot",
        "morgan-stanley",
        "games24x7",
    ):
        assert sources[company_id].enabled is False
        assert sources[company_id].adapter_type.value == "search_only"


def test_phase12_package_b_freshteam_cohort_uses_verified_public_boards() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    sources = {entry.source.company_id: entry.source for entry in registry.entries}

    for company_id, account in (("locus", "locus"), ("jio-platforms-haptik", "haptik")):
        source = sources[company_id]
        assert source.enabled is True
        assert source.status.value == "enabled"
        assert source.adapter_type.value == "freshteam"
        assert source.adapter_parameters == {"account": account}
        assert source.identity_strategy.value == "external_id"
        assert source.detail_strategy.value == "detail_page"
        assert source.date_strategy.field_name == "datePosted"
        assert source.date_strategy.verified_as_publication is True


def test_phase12_package_c_second_cohort_activates_verified_custom_sources() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    sources = {entry.source.company_id: entry.source for entry in registry.entries}

    stripe = sources["stripe"]
    assert stripe.enabled is True
    assert stripe.status.value == "enabled"
    assert stripe.adapter_type.value == "custom"
    assert stripe.adapter_parameters == {"adapter_key": "stripe_careers_index"}
    assert stripe.identity_strategy.value == "external_id"
    assert stripe.date_strategy.field_name == "datePosted"
    assert stripe.date_strategy.basis.value == "published"
    assert stripe.date_strategy.verified_as_publication is True
    assert stripe.detail_strategy.value == "detail_page"

    for company_id, publisher, feed_url in (
        (
            "servicenow",
            "ServiceNow",
            "https://careers.servicenow.com/jobs/xml/?rss=true",
        ),
        ("coupang", "Coupang", "https://www.coupang.jobs/en/jobs/xml/?rss=true"),
    ):
        source = sources[company_id]
        assert source.enabled is True
        assert source.status.value == "enabled"
        assert source.adapter_type.value == "custom"
        assert source.adapter_parameters == {
            "adapter_key": "pageup_xml_feed",
            "feed_url": feed_url,
            "publisher": publisher,
        }
        assert source.identity_strategy.value == "external_id"
        assert source.date_strategy.field_name == "date"
        assert source.date_strategy.basis.value == "published"
        assert source.date_strategy.verified_as_publication is True
        assert source.detail_strategy.value == "listing_payload"

    flipkart = sources["flipkart"]
    assert flipkart.enabled is False
    assert flipkart.status.value == "proposed"
    assert flipkart.adapter_type.value == "search_only"
    assert flipkart.exception_reason is not None


def test_phase12_package_c_third_cohort_replaces_third_party_sources() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    sources = {entry.source.company_id: entry.source for entry in registry.entries}

    deshaw = sources["d-e-shaw-india"]
    assert deshaw.enabled is True
    assert deshaw.status.value == "enabled"
    assert deshaw.careers_url == "https://www.deshawindia.com/careers"
    assert deshaw.adapter_type.value == "custom"
    assert deshaw.adapter_parameters == {"adapter_key": "deshaw_india_index"}
    assert deshaw.identity_strategy.value == "external_id"
    assert deshaw.date_strategy.field_name is None
    assert deshaw.date_strategy.basis.value == "unknown"
    assert deshaw.date_strategy.verified_as_publication is False
    assert deshaw.detail_strategy.value == "listing_payload"

    squarepoint = sources["squarepoint-capital"]
    assert squarepoint.enabled is True
    assert squarepoint.status.value == "enabled"
    assert squarepoint.careers_url == ("https://www.squarepoint-capital.com/open-opportunities")
    assert squarepoint.adapter_type.value == "greenhouse"
    assert squarepoint.adapter_parameters == {"board_token": "squarepointcapital"}
    assert squarepoint.identity_strategy.value == "external_id"
    assert squarepoint.date_strategy.field_name == "first_published"
    assert squarepoint.date_strategy.basis.value == "published"
    assert squarepoint.date_strategy.verified_as_publication is True
    assert squarepoint.detail_strategy.value == "listing_payload"


def test_phase12_package_c_fourth_cohort_activates_validated_sources() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    sources = {entry.source.company_id: entry.source for entry in registry.entries}
    altimate = sources["altimate-ai"]

    assert altimate.enabled is True
    assert altimate.status.value == "enabled"
    assert altimate.careers_url == "https://jobs.ashbyhq.com/altimate"
    assert altimate.adapter_type.value == "ashby"
    assert altimate.adapter_parameters == {"board_name": "altimate"}
    assert altimate.identity_strategy.value == "external_id"
    assert altimate.date_strategy.field_name == "publishedAt"
    assert altimate.date_strategy.basis.value == "published"
    assert altimate.date_strategy.verified_as_publication is True
    assert altimate.detail_strategy.value == "listing_payload"

    aganitha = sources["aganitha"]
    assert aganitha.enabled is True
    assert aganitha.adapter_type.value == "custom"
    assert aganitha.adapter_parameters == {"adapter_key": "aganitha_careers_index"}
    assert aganitha.date_strategy.basis.value == "unknown"
    assert aganitha.detail_strategy.value == "detail_page"

    galaxeye = sources["galaxeye"]
    assert galaxeye.enabled is True
    assert galaxeye.adapter_type.value == "custom"
    assert galaxeye.adapter_parameters == {"adapter_key": "galaxeye_zoho_rss"}
    assert galaxeye.date_strategy.field_name == "pubDate"
    assert galaxeye.date_strategy.verified_as_publication is True
    assert galaxeye.detail_strategy.value == "listing_payload"

    gnani = sources["gnani-ai"]
    assert gnani.enabled is True
    assert gnani.adapter_type.value == "custom"
    assert gnani.adapter_parameters == {"adapter_key": "gnani_careers_api"}
    assert gnani.date_strategy.field_name == "positionPublishDate"
    assert gnani.date_strategy.verified_as_publication is True
    assert gnani.detail_strategy.value == "detail_page"


def test_phase12_package_c_fifth_cohort_activates_validated_p1_sources() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    sources = {entry.source.company_id: entry.source for entry in registry.entries}

    atlassian = sources["atlassian"]
    assert atlassian.enabled is True
    assert atlassian.adapter_type.value == "custom"
    assert atlassian.adapter_parameters == {"adapter_key": "atlassian_careers_inventory"}
    assert atlassian.date_strategy.field_name == "portalJobPost.updatedDate"
    assert atlassian.date_strategy.basis.value == "unknown"
    assert atlassian.detail_strategy.value == "listing_payload"

    gitlab = sources["gitlab"]
    assert gitlab.enabled is True
    assert gitlab.adapter_type.value == "greenhouse"
    assert gitlab.adapter_parameters == {"board_token": "gitlab"}
    assert gitlab.date_strategy.field_name == "first_published"
    assert gitlab.date_strategy.verified_as_publication is True
    assert gitlab.detail_strategy.value == "listing_payload"

    qure = sources["qure-ai"]
    assert qure.enabled is True
    assert qure.adapter_type.value == "custom"
    assert qure.adapter_parameters == {"adapter_key": "qure_zoho_embedded"}
    assert qure.date_strategy.field_name == "Date_Opened"
    assert qure.date_strategy.basis.value == "unknown"
    assert qure.detail_strategy.value == "listing_payload"

    airbnb = sources["airbnb"]
    assert airbnb.enabled is True
    assert airbnb.adapter_type.value == "custom"
    assert airbnb.adapter_parameters == {"adapter_key": "airbnb_careers_pages"}
    assert airbnb.date_strategy.field_name == "WebPage.datePublished"
    assert airbnb.date_strategy.basis.value == "unknown"
    assert airbnb.detail_strategy.value == "detail_page"

    linkedin = sources["linkedin"]
    assert linkedin.enabled is False
    assert linkedin.adapter_type.value == "search_only"
    assert linkedin.exception_reason is not None


def test_phase12_package_c_sixth_cohort_activates_six_validated_p1_sources() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    sources = {entry.source.company_id: entry.source for entry in registry.entries}

    intuit = sources["intuit"]
    assert intuit.enabled is True
    assert intuit.adapter_type.value == "custom"
    assert intuit.adapter_parameters == {"adapter_key": "intuit_bengaluru_pages"}
    assert intuit.date_strategy.field_name == "JobPosting.datePosted"
    assert intuit.date_strategy.verified_as_publication is True
    assert intuit.detail_strategy.value == "detail_page"

    twilio = sources["twilio"]
    assert twilio.enabled is True
    assert twilio.adapter_type.value == "custom"
    assert twilio.adapter_parameters == {"adapter_key": "twilio_public_careers_api"}
    assert twilio.date_strategy.field_name == "efcustomTextPostDate"
    assert twilio.date_strategy.verified_as_publication is True
    assert twilio.detail_strategy.value == "detail_endpoint"

    meesho = sources["meesho"]
    assert meesho.enabled is True
    assert meesho.adapter_type.value == "lever"
    assert meesho.adapter_parameters == {"site": "meesho"}
    assert meesho.date_strategy.field_name == "createdAt"
    assert meesho.date_strategy.basis.value == "unknown"

    phonepe = sources["phonepe"]
    assert phonepe.enabled is True
    assert phonepe.adapter_type.value == "smartrecruiters"
    assert phonepe.adapter_parameters == {"company_identifier": "PHONEPELIMITED"}
    assert phonepe.date_strategy.field_name == "releasedDate"
    assert phonepe.detail_strategy.value == "detail_endpoint"

    swiggy = sources["swiggy"]
    assert swiggy.enabled is True
    assert swiggy.adapter_type.value == "custom"
    assert swiggy.adapter_parameters == {"adapter_key": "swiggy_mynexthire_inventory"}
    assert swiggy.date_strategy.field_name == "approvedOn"
    assert swiggy.date_strategy.basis.value == "unknown"
    assert swiggy.detail_strategy.value == "listing_payload"

    tower = sources["tower-research-capital"]
    assert tower.enabled is True
    assert tower.adapter_type.value == "greenhouse"
    assert tower.adapter_parameters == {"board_token": "towerresearchcapital"}
    assert tower.date_strategy.field_name == "first_published"
    assert tower.detail_strategy.value == "listing_payload"

    roku = sources["roku"]
    assert roku.enabled is False
    assert roku.adapter_type.value == "search_only"
    assert roku.exception_reason is not None
    assert "AWS WAF" in roku.exception_reason


def test_phase12_package_c_seventh_cohort_activates_eight_verified_sources() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    sources = {entry.source.company_id: entry.source for entry in registry.entries}

    for company_id, board_token in (
        ("moloco", "moloco"),
        ("inmobi", "inmobi"),
        ("truefoundry", "truefoundry"),
    ):
        source = sources[company_id]
        assert source.enabled is True
        assert source.status.value == "enabled"
        assert source.adapter_type.value == "greenhouse"
        assert source.adapter_parameters == {"board_token": board_token}
        assert source.identity_strategy.value == "external_id"
        assert source.date_strategy.field_name == "first_published"
        assert source.date_strategy.verified_as_publication is True
        assert source.detail_strategy.value == "listing_payload"

    for company_id, host, tenant, site in (
        (
            "salesforce",
            "salesforce.wd12.myworkdayjobs.com",
            "salesforce",
            "External_Career_Site",
        ),
        ("postman", "postman.wd108.myworkdayjobs.com", "postman", "careers"),
    ):
        source = sources[company_id]
        assert source.enabled is True
        assert source.status.value == "enabled"
        assert source.adapter_type.value == "workday"
        assert source.adapter_parameters == {"host": host, "tenant": tenant, "site": site}
        assert source.identity_strategy.value == "external_id"
        assert source.date_strategy.field_name == "postedOn"
        assert source.date_strategy.basis.value == "unknown"
        assert source.date_strategy.verified_as_publication is False
        assert source.detail_strategy.value == "detail_endpoint"

    booking = sources["booking-com"]
    assert booking.enabled is True
    assert booking.status.value == "enabled"
    assert booking.careers_url == "https://jobs.booking.com/booking/jobs"
    assert booking.adapter_type.value == "custom"
    assert booking.adapter_parameters == {"adapter_key": "booking_jibe_inventory"}
    assert booking.identity_strategy.value == "external_id"
    assert booking.date_strategy.field_name == "posted_date"
    assert booking.date_strategy.basis.value == "published"
    assert booking.date_strategy.verified_as_publication is True
    assert booking.detail_strategy.value == "listing_payload"

    navi = sources["navi"]
    assert navi.enabled is True
    assert navi.careers_url == "https://navi.com/careers/jobs"
    assert navi.adapter_type.value == "custom"
    assert navi.adapter_parameters == {"adapter_key": "navi_public_careers_api"}
    assert navi.date_strategy.field_name == "PublishedDate"
    assert navi.date_strategy.verified_as_publication is True
    assert navi.detail_strategy.value == "listing_payload"

    quadeye = sources["quadeye"]
    assert quadeye.enabled is True
    assert quadeye.careers_url == "https://www.quadeye.com/jobs"
    assert quadeye.adapter_type.value == "custom"
    assert quadeye.adapter_parameters == {"adapter_key": "quadeye_zoho_proxy"}
    assert quadeye.date_strategy.field_name == "Date_Opened"
    assert quadeye.date_strategy.basis.value == "unknown"
    assert quadeye.date_strategy.verified_as_publication is False
    assert quadeye.detail_strategy.value == "listing_payload"


def test_phase12_package_c_eighth_cohort_activates_shared_host_pcsx_source() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    source = next(
        entry.source for entry in registry.entries if entry.source.company_id == "eightfold-ai"
    )

    assert source.enabled is True
    assert source.status.value == "enabled"
    assert source.careers_url == ("https://app.eightfold.ai/careers?domain=volkscience.com&hl=en")
    assert source.adapter_type.value == "custom"
    assert source.adapter_parameters == {
        "adapter_key": "pcsx_public_careers",
        "host": "app.eightfold.ai",
        "domain": "volkscience.com",
    }
    assert source.identity_strategy.value == "external_id"
    assert source.date_strategy.field_name == "postedTs"
    assert source.date_strategy.basis.value == "unknown"
    assert source.date_strategy.verified_as_publication is False
    assert source.detail_strategy.value == "detail_endpoint"


def test_phase12_package_c_ninth_cohort_activates_index_exchange_inventory() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    source = next(
        entry.source for entry in registry.entries if entry.source.company_id == "index-exchange"
    )

    assert source.enabled is True
    assert source.status.value == "enabled"
    assert source.careers_url == "https://www.indexexchange.com/careers/opportunities/"
    assert source.adapter_type.value == "custom"
    assert source.adapter_parameters == {"adapter_key": "index_exchange_official_inventory"}
    assert source.identity_strategy.value == "external_id"
    assert source.date_strategy.field_name is None
    assert source.date_strategy.basis.value == "unknown"
    assert source.detail_strategy.value == "detail_page"

    sp_global = next(
        entry.source for entry in registry.entries if entry.source.company_id == "s-and-p-global"
    )
    assert sp_global.enabled is True
    assert sp_global.status.value == "enabled"
    assert sp_global.careers_url == "https://spgi.wd5.myworkdayjobs.com/SPGI_Careers"
    assert sp_global.adapter_type.value == "workday"
    assert sp_global.adapter_parameters == {
        "host": "spgi.wd5.myworkdayjobs.com",
        "tenant": "spgi",
        "site": "SPGI_Careers",
    }
    assert sp_global.identity_strategy.value == "external_id"
    assert sp_global.date_strategy.field_name == "postedOn"
    assert sp_global.date_strategy.basis.value == "unknown"


def test_phase12_package_c_tenth_cohort_activates_adobe_and_oracle() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    sources = {entry.source.company_id: entry.source for entry in registry.entries}

    adobe = sources["adobe"]
    assert adobe.enabled is True
    assert adobe.adapter_type.value == "workday"
    assert adobe.careers_url == "https://adobe.wd5.myworkdayjobs.com/external_experienced"
    assert adobe.adapter_parameters == {
        "host": "adobe.wd5.myworkdayjobs.com",
        "tenant": "adobe",
        "site": "external_experienced",
    }
    assert adobe.date_strategy.field_name == "postedOn"
    assert adobe.date_strategy.basis.value == "unknown"

    oracle = sources["oracle-oci"]
    assert oracle.enabled is True
    assert oracle.adapter_type.value == "oracle_cloud"
    assert oracle.careers_url == (
        "https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_45001/jobs"
    )
    assert oracle.adapter_parameters == {
        "host": "eeho.fa.us2.oraclecloud.com",
        "site_number": "CX_45001",
    }
    assert oracle.date_strategy.field_name == "PostedDate"
    assert oracle.date_strategy.basis.value == "published"
    assert oracle.date_strategy.verified_as_publication is True


def test_phase12_package_b_corrects_payu_to_its_official_successfactors_board() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    payu = next(entry.source for entry in registry.entries if entry.source.company_id == "payu")

    assert payu.enabled is True
    assert payu.adapter_type.value == "successfactors"
    assert payu.adapter_parameters == {
        "host": "careers.payu.in",
        "category_path": "/PayU/go/_/514880/",
    }
    assert payu.identity_strategy.value == "external_id"
    assert payu.date_strategy.field_name == "datePosted"
    assert payu.date_strategy.verified_as_publication is True


def test_phase12_package_b_activates_sanas_rippling_with_uncertain_creation_date() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    sanas = next(entry.source for entry in registry.entries if entry.source.company_id == "sanas")

    assert sanas.enabled is True
    assert sanas.adapter_type.value == "rippling"
    assert sanas.adapter_parameters == {"board_slug": "sanas"}
    assert sanas.date_strategy.field_name == "createdOn"
    assert sanas.date_strategy.basis.value == "unknown"
    assert sanas.date_strategy.verified_as_publication is False


def test_phase12_package_b_activates_groww_sensehq_with_uncertain_creation_date() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    groww = next(entry.source for entry in registry.entries if entry.source.company_id == "groww")

    assert groww.enabled is True
    assert groww.adapter_type.value == "sensehq"
    assert groww.adapter_parameters == {"career_subdomain": "groww"}
    assert groww.detail_strategy.value == "listing_payload"
    assert groww.date_strategy.field_name == "created_on"
    assert groww.date_strategy.basis.value == "unknown"
    assert groww.date_strategy.verified_as_publication is False


def test_phase12_package_b_activates_coinswitch_recruiterflow_with_detail_dates() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    coinswitch = next(
        entry.source for entry in registry.entries if entry.source.company_id == "coinswitch"
    )

    assert coinswitch.enabled is True
    assert coinswitch.status.value == "enabled"
    assert coinswitch.careers_url == "https://recruiterflow.com/coinswitch/jobs"
    assert coinswitch.adapter_type.value == "recruiterflow"
    assert coinswitch.adapter_parameters == {"board_slug": "coinswitch"}
    assert coinswitch.identity_strategy.value == "external_id"
    assert coinswitch.detail_strategy.value == "detail_page"
    assert coinswitch.date_strategy.field_name == "datePosted"
    assert coinswitch.date_strategy.basis.value == "published"
    assert coinswitch.date_strategy.verified_as_publication is True


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


def test_amazon_aws_uses_complete_india_search_with_full_listing_payloads() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    amazon = next(
        entry.source for entry in registry.entries if entry.source.company_id == "amazon-aws"
    )

    assert amazon.adapter_type.value == "custom"
    assert amazon.careers_url == "https://www.amazon.jobs/en/search?country=IND&sort=recent"
    assert amazon.adapter_parameters == {"adapter_key": "amazon_jobs_india"}
    assert amazon.status.value == "enabled"
    assert amazon.identity_strategy.value == "external_id"
    assert amazon.date_strategy.field_name == "posted_date"
    assert amazon.date_strategy.basis.value == "published"
    assert amazon.date_strategy.verified_as_publication is True
    assert amazon.detail_strategy.value == "listing_payload"
    assert amazon.enabled is True


def test_google_uses_count_checked_india_search_with_deferred_details() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    google = next(entry.source for entry in registry.entries if entry.source.company_id == "google")

    assert google.adapter_type.value == "custom"
    assert google.careers_url == (
        "https://www.google.com/about/careers/applications/jobs/results/?location=India"
    )
    assert google.adapter_parameters == {"adapter_key": "google_careers_india"}
    assert google.status.value == "enabled"
    assert google.identity_strategy.value == "external_id"
    assert google.date_strategy.field_name is None
    assert google.date_strategy.basis.value == "unknown"
    assert google.date_strategy.verified_as_publication is False
    assert google.detail_strategy.value == "detail_page"
    assert google.enabled is True


def test_apple_uses_count_checked_hydration_with_mixed_date_evidence() -> None:
    registry = load_company_registry(Path("config/company_sources.json"))
    apple = next(entry.source for entry in registry.entries if entry.source.company_id == "apple")

    assert apple.adapter_type.value == "custom"
    assert apple.careers_url == "https://jobs.apple.com/en-us/search?location=india-INDC"
    assert apple.adapter_parameters == {"adapter_key": "apple_jobs_india"}
    assert apple.status.value == "enabled"
    assert apple.identity_strategy.value == "external_id"
    assert apple.date_strategy.field_name == "postDateInGMT"
    assert apple.date_strategy.basis.value == "published"
    assert apple.date_strategy.verified_as_publication is True
    assert apple.detail_strategy.value == "detail_page"
    assert apple.enabled is True
