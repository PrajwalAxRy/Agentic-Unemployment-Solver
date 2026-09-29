"""Checks that mandatory human-checkpoint artifacts match tracked inventory."""

import json
from collections import Counter
from pathlib import Path


def test_h2_review_artifact_has_required_decision_sections_and_counts() -> None:
    review = Path("docs/reviews/h2_source_inventory_review.md").read_text(encoding="utf-8")
    payload = json.loads(Path("data/source_discovery_proposals.json").read_text(encoding="utf-8"))
    statuses = Counter(item["status"] for item in payload["proposals"])

    assert "APPROVED — proceed instruction received 2026-09-20" in review
    assert f"{statuses['auto_verified']} read-only verified sources" in review
    assert f"{statuses['access_concern']} access-concern sources" in review
    assert f"{statuses['conflict']} conflicting or non-enumerating sources" in review
    assert f"{statuses['proposed']} responsive but oversized structured boards" in review
    assert "Access-policy concerns requiring approval" in review
    assert "Conflicting or non-enumerating proposals requiring inspection" in review
    assert "Verified search-only sources requiring custom adapters" in review
    assert (
        "Ashby, Greenhouse, Lever, Workday, and Darwinbox have now passed full "
        "adapter-group validation" in review
    )
    assert "Canonical scope: 330 of 330 companies" in review


def test_phase3_ashby_review_records_complete_group_validation() -> None:
    review = Path("docs/reviews/phase3_ashby_validation.md").read_text(encoding="utf-8")

    assert "Status: **passed**" in review
    assert "Companies: 25" in review
    assert 'Outcomes: `{"empty": 1, "success": 24}`' in review
    assert "Observed jobs: 1027" in review
    assert "Missing required fields: 0" in review
    assert "Cerebras Systems required the exact case-sensitive board name" in review
    assert "WisdomAI had moved" in review


def test_phase4_greenhouse_review_records_complete_group_validation() -> None:
    review = Path("docs/reviews/phase4_greenhouse_validation.md").read_text(encoding="utf-8")

    assert "Status: **passed**" in review
    assert "Companies: 25" in review
    assert 'Outcomes: `{"success": 25}`' in review
    assert "Observed jobs: 2268" in review
    assert "Missing required fields: 0" in review
    assert (
        'Date evidence: `{"first_seen": 0, "published": 2265, "unknown": 0, "updated": 3}`'
        in review
    )
    assert "Clipboard Health's official careers page now links to the public Ashby board" in review


def test_phase4_lever_review_records_complete_group_validation() -> None:
    review = Path("docs/reviews/phase4_lever_validation.md").read_text(encoding="utf-8")

    assert "Status: **passed for all current Lever mappings**" in review
    assert "Companies: 11" in review
    assert 'Outcomes: `{"success": 11}`' in review
    assert "Observed jobs: 386" in review
    assert "Jobs missing descriptions: 17" in review
    assert (
        'Date evidence: `{"first_seen": 0, "published": 0, "unknown": 386, "updated": 0}`' in review
    )
    assert "Dream Sports' official careers page still links to the obsolete" in review


def test_phase4_oracle_cloud_review_records_complete_group_validation() -> None:
    review = Path("docs/reviews/phase4_oracle_cloud_validation.md").read_text(encoding="utf-8")

    assert "Status: **passed for both Oracle Cloud mappings**" in review
    assert "| Uber | 532 | 3 | 0 | 532 `PostedDate` published |" in review
    assert "| JPMorganChase | 7,355 | 37 | 0 | 7,355 `PostedDate` published |" in review
    assert "The inventory total can change during a long scan" in review
    assert "the next correct offset is still the prior offset plus the requested limit" in review
    assert "H3 and H4 were not triggered" in review


def test_phase4_successfactors_review_records_mapping_and_correction() -> None:
    review = Path("docs/reviews/phase4_successfactors_validation.md").read_text(encoding="utf-8")

    assert "Status: **passed for the current SuccessFactors mapping**" in review
    assert "| SAP | 46 | 2 | 0 | 46 unknown until detail retrieval |" in review
    assert "posting `1280449101` matched the listing identity" in review
    assert "9,843-character normalized description" in review
    assert "Moody's official public inventory is hosted by Radancy" in review
    assert "This correction does not trigger H4" in review


def test_phase4_jobvite_review_records_complete_group_validation() -> None:
    review = Path("docs/reviews/phase4_jobvite_validation.md").read_text(encoding="utf-8")

    assert "Status: **passed for the Jobvite mapping**" in review
    assert "| SiMa.ai | 18 | 1 | 0 | 18 unknown until detail retrieval |" in review
    assert "18 unique job links and no pagination control" in review
    assert "Jobvite ID `oCzUzfwo` matched the listing identity" in review
    assert "1,705-character normalized description" in review
    assert "H3 and H4 were not triggered" in review


def test_phase4_coverage_review_records_reconciled_full_registry_gate() -> None:
    review = Path("docs/reviews/phase4_adapter_coverage_completion.md").read_text(encoding="utf-8")

    assert "Status: **passed**" in review
    assert "The registry has 86 enabled and 244 disabled records" in review
    assert 'Outcomes: `{"empty": 2, "success": 84}`' in review
    assert "Observed jobs: 26,107" in review
    assert "Fetched pages: 661" in review
    assert "Failed, blocked, partial, or suspicious companies: 0" in review
    assert (
        'Date evidence: `{"first_seen": 0, "published": 16142, "unknown": 9962, '
        '"updated": 3}`' in review
    )
    assert "NVIDIA and PayPal; H4-approved official-page manual fallbacks" in review
    assert "Phase 4 is complete" in review


def test_phase12_package_a_review_records_activation_and_full_registry_gate() -> None:
    review = Path("docs/reviews/phase12_package_a_validation.md").read_text(encoding="utf-8")

    assert "21 existing-adapter sources activated; 13 candidates failed closed" in review
    assert "6,113 current listings over 209 fetched pages" in review
    assert "103 successful, three verified empty, one" in review
    assert "32,198 observed listings over 867 fetched pages" in review
    assert "No Package A source was failed, blocked, partial, or suspicious" in review
    assert "Package D and\nPackage E remain unapproved" in review


def test_phase12_package_b_review_records_activation_and_full_registry_gate() -> None:
    review = Path("docs/reviews/phase12_package_b_validation.md").read_text(encoding="utf-8")

    assert "6 reusable-family sources activated; 8 candidates failed closed" in review
    assert "activated cohort accounts for 185 current listings" in review
    assert "109 successful, three verified empty, one" in review
    assert "32,379 observed listings over 880 fetched pages" in review
    assert "Every Package B source succeeded" in review
    assert "pytest reported **502 passed**" in review
    assert "Packages D and E remain unapproved" in review


def test_phase12_package_c_cohort1_records_activation_and_failed_closed_source() -> None:
    review = Path("docs/reviews/phase12_package_c_cohort1_validation.md").read_text(
        encoding="utf-8"
    )

    assert "3 deterministic custom sources activated; 1 candidate failed closed" in review
    assert "activated cohort accounts for **2,804 current listings**" in review
    assert "233 unique jobs over 24 pages" in review
    assert "registry entry remains disabled and `search_only`" in review
    assert "112 successful, three verified empty" in review
    assert "Amazon / AWS, Google, and Apple all passed" in review
    assert "pytest\nreported **526 passed**" in review
    assert "Packages D and E remain\nunapproved" in review


def test_h5_review_records_full_registry_date_coverage_and_approved_decision() -> None:
    review = Path("docs/reviews/h5_date_coverage_review.md").read_text(encoding="utf-8")

    assert "**Complete — Human checkpoint H5: option 4, the recommended hybrid policy" in review
    assert 'Enabled companies: 86; outcomes: `{"empty": 2, "success": 84}`' in review
    assert "Observed listings: 26,122" in review
    assert "Valid identities: 26,122; valid canonical URLs: 26,122" in review
    assert "| Every observed listing reliable | 49 | 56.98% |" in review
    assert "| Mixed reliable and uncertain | 5 | 5.81% |" in review
    assert "| No reliable publication dates | 30 | 34.88% |" in review
    assert "| Reliable publication evidence | 15,911 | 60.91% |" in review
    assert "| Measurement pool, no age decision | 10,211 | 39.09% |" in review
    assert "First-seen timestamps available in this initial measurement: 0" in review
    assert "**Recommendation: option 4.**" in review
    assert "The user approved option 4" in review
    assert "search-profile version `1.1.0`" in review


def test_h6_review_has_required_samples_and_coverage() -> None:
    review = Path("docs/reviews/h6_filter_review.md").read_text(encoding="utf-8")

    assert "**Complete — Human checkpoint H6: role and location filtering approved" in review
    assert "Listings observed: 25,960" in review
    assert "| K20 |" in review
    assert "| X20 |" in review
    assert review.count("| K01 |") == 1
    assert review.count("| X01 |") == 1
    assert review.count("| L01 |") == 1
    assert "structured_india_location_code" in review
    assert "explicitly approved H6 on 2026-09-22 without row-labelled corrections" in review
    for family in (
        "agents_and_tooling",
        "ai_software_and_product_engineering",
        "conditional_description",
        "generative_ai_engineering",
        "ml_engineering",
        "ml_platform_and_infrastructure",
        "model_systems_and_optimization",
        "research_and_applied_science",
        "retrieval_search_and_rag",
    ):
        assert family in review


def test_phase7_review_records_clean_full_registry_idempotency_gate() -> None:
    review = Path("docs/reviews/phase7_persistence_validation.md").read_text(encoding="utf-8")

    assert "**Passed on 2026-09-23.**" in review
    assert "all 86 enabled" in review
    assert "26,051 listings" in review
    assert "333 candidates" in review
    assert "zero new identities" in review
    assert "84 successful and two" in review
    assert "336 identities" in review
    assert "conditional checkpoint H7 was not" in review
    assert "356 tests" in review


def test_h8_configuration_documents_redacted_provider_setup() -> None:
    guide = Path("docs/06_llm_provider_configuration.md").read_text(encoding="utf-8")
    example = Path(".env.example").read_text(encoding="utf-8")
    ignore = Path(".gitignore").read_text(encoding="utf-8")

    assert "`gpt-5.6-luna`" in guide
    assert "https://llm-api.amd.com/Unified/v1" in guide
    assert "`Ocp-Apim-Subscription-Key`" in guide
    assert "job-finder check-llm --presence-only" in guide
    assert "job-finder check-llm" in guide
    assert "Do not commit `.env`" in guide
    assert "LLM_GATEWAY_KEY=\n" in example
    assert "JOB_FINDER_LLM_MAX_REQUESTS=500" in example
    assert ".env\n" in ignore


def test_h9_review_records_quality_gate_and_live_evidence() -> None:
    review = Path("docs/reviews/h9_seniority_quality_review.md").read_text(encoding="utf-8")

    assert "**APPROVED — Human checkpoint H9 completed on 2026-09-23.**" in review
    assert "approved the recommended first-release threshold and uncertainty policy" in review
    assert "prompt `1.0.1`" in review
    assert "Exact decision agreement: 20/20 (100.00%)" in review
    assert "invalid/manual-review outcomes: 0" in review
    assert "False acceptances: 0; false rejections: 0; ambiguity errors: 0" in review
    assert 'source outcomes: `{"empty": 2, "success": 84}`; healthy: `true`' in review
    assert "Limited live batch: 8 decisions" in review
    assert "All eight live decisions were reviewed" in review
    assert "Completed decisions with locally verified verbatim description evidence: 28" in review


def test_manual_scan_runbook_documents_outcomes_state_and_h10_review() -> None:
    runbook = Path("docs/07_scan_runbook.md").read_text(encoding="utf-8")

    assert "uv run --locked job-finder scan" in runbook
    assert "reports/latest_scan.md" in runbook
    assert "reports/latest_scan.json" in runbook
    assert "Zero matching" in runbook
    assert "Exit status is `0`" in runbook
    assert "state inspect" in runbook
    assert "state backup" in runbook
    assert "state restore" in runbook
    assert "H10 usability checklist" in runbook
    assert "Where are state inspection, backup, restore, and reset instructions?" in runbook
    assert "bounded progress" in runbook
    assert "pending and is retried" in runbook
    assert "How to answer the H10 review" in runbook
    assert "Exact place to look" in runbook
    assert "Inclusion/review reasons clear: yes/no" in runbook
    assert "The separate **Unsupported and blocked sources** table" in runbook


def test_h10_review_records_full_registry_evidence_and_usability_approval() -> None:
    review = Path("docs/reviews/h10_usability_review.md").read_text(encoding="utf-8")

    assert "APPROVED — Human checkpoint H10 completed on 2026-09-23" in review
    assert "replied `usable`" in review
    assert "uv run --locked job-finder scan" in review
    assert "reports/latest_scan.md" in review
    assert "reports/phase9_scan_postfix.md" in review
    assert "84 successful, two verified empty, and zero failed sources" in review
    assert "Zero new identities, 311 suppressed duplicates" in review
    assert "zero disabled rows without an explanation" in review
    assert "Reply `usable`" in review


def test_phase10_runbook_documents_resilience_and_guarded_repair() -> None:
    runbook = Path("docs/08_source_resilience_and_repair.md").read_text(encoding="utf-8")

    for category in (
        "temporary_availability",
        "rate_limit",
        "configuration_error",
        "source_moved",
        "schema_change",
        "parser_defect",
        "access_restriction",
        "unsupported_source",
    ):
        assert category in runbook
    assert "result_count_collapse" in runbook
    assert "future_publication_date" in runbook
    assert "stale_publication_dates" in runbook
    assert "verify-sources" in runbook
    assert "--all-enabled" in runbook
    assert "repair build-request" in runbook
    assert "repair validate-proposal" in runbook
    assert "repair test-proposal" in runbook
    assert "The repair system has no activation command" in runbook
    assert "approve <proposal-id>" in runbook


def test_h11_review_records_approved_sap_repair_and_final_evidence() -> None:
    review = Path("docs/reviews/phase10_h11_sap_repair.md").read_text(encoding="utf-8")

    assert "APPROVED — Human checkpoint H11 completed on 2026-09-25" in review
    assert "repair-1ddc97abb012ee26" in review
    assert "Proposal status: `approved and applied`" in review
    assert "the user replied `approve repair-1ddc97abb012ee26`" in review
    assert "Repair commit: `4c4b2c8`" in review
    assert '"https://jobs.sap.com/go/SAP-Jobs-in-India/851201/"' in review
    assert '"https://careers.sap.com/go/SAP-Jobs-in-India/851201/"' in review
    assert '"host": "jobs.sap.com"' in review
    assert '"host": "careers.sap.com"' in review
    assert "47 unique jobs across two pages" in review
    assert "requisition `1280449101`" in review
    assert "82 succeeded, two" in review
    assert "no false failure category" in review
    assert "Clipboard Health (Ashby, 36 jobs)" in review
    assert "Freshworks" in review and "125 jobs on two pages" in review
    assert "external transient" in review
    assert "rather than 21 simultaneous source regressions" in review
    assert "461 tests" in review
    assert "48 jobs across two pages" in review
    assert "26,193" in review and "660 pages" in review
    assert "83 sources succeeded, two" in review
    assert "zero failure categories" in review
    assert "parent of repair commit `4c4b2c8`" in review


def test_phase11_pilot_log_records_third_clean_day_and_release_approval() -> None:
    review = Path("docs/reviews/phase11_pilot_log.md").read_text(encoding="utf-8")

    assert "third clean pilot day passed on 2026-09-28" in review
    assert "H13 approved the first release and annotated\ntag `v0.1.0`" in review
    assert "2026-09-25, 2026-09-26, and 2026-09-28" in review
    assert "`0.2.0-phase4`" in review
    assert "version `1.1.2`" in review
    assert "`d462aa976b4a16cdf69803c426c7cb03451a3f51`" in review
    assert "394 records: 22 pending, 195 completed, and 177" in review
    assert "395 records: 21 pending, 196\n  completed, and 178 failed" in review
    assert "`scan-20260925T135115Z-dc5432db`" in review
    assert "`scan-20260925T144452Z-39d54451`" in review
    assert "`scan-20260926T000739Z-2cef6bde`" in review
    assert "`scan-20260927T173616Z-6766cac6`" in review
    assert "`scan-20260927T193726Z-8c89b1a8`" in review
    assert "Zero new identities; 311 completed duplicates suppressed" in review
    assert "zero new identities, suppressed 303 completed duplicates" in review
    assert "All 34 review rows were inspected" in review
    assert "All 29 review rows were inspected" in review
    assert "All 28 review rows were inspected" in review
    assert "`repair-067463ff973ca40d`" in review
    assert "`210786170` nor `210788786`" in review
    assert "`Data Scientist Associate` (`210794862`)" in review
    assert "84 successful sources, Deeptune and Rapido as the two valid-empty" in review
    assert "`d0ba02e`" in review
    assert "`719976e`" in review
    assert "`2161d0e`" in review
    assert "`fc9734c`" in review
    assert "`d462aa9`" in review
    assert "strict mypy across 90 source files, and 477 tests" in review


def test_phase11_atomicwork_review_records_custom_adapter_approval() -> None:
    review = Path("docs/reviews/phase11_atomicwork_coverage_review.md").read_text(encoding="utf-8")

    assert "H4 approved custom-adapter work and H11 approved activation on 2026-09-28" in review
    assert "The user selected `build Atomicwork custom adapter`" in review
    assert "`approve repair-067463ff973ca40d` at H11" in review
    assert "`repair-067463ff973ca40d`" in review
    assert "`source_moved`" in review
    assert "returns HTTP 404" in review
    assert "exactly the same six" in review
    assert "activation commit `d462aa9`" in review
    assert "zero persisted Atomicwork candidate records" in review
    assert "post-activation 2026-09-28 scan completed with zero failed sources" in review


def test_phase11_atomicwork_h11_review_records_approved_activation() -> None:
    review = Path("docs/reviews/phase11_atomicwork_h11_activation.md").read_text(encoding="utf-8")

    assert "APPROVED — Human checkpoint H11 completed on 2026-09-28" in review
    assert "`repair-067463ff973ca40d`" in review
    assert "`fc9734c`" in review
    assert "Activation commit: `d462aa9`" in review
    assert "the user replied `approve repair-067463ff973ca40d`" in review
    assert '"adapter_type": "greenhouse"' in review
    assert '"adapter_type": "custom"' in review
    assert '"adapter_key": "atomicwork_webflow"' in review
    assert '"basis": "unknown"' in review
    assert "six unique jobs" in review
    assert "pytest: 474 passed" in review
    assert "83 sources succeeded" in review
    assert "zero failed sources" in review
    assert "26,118 jobs across 658 pages" in review
    assert "`scan-20260927T193726Z-8c89b1a8`" in review
    assert "395 records: 21 pending, 196 completed, and 178 failed" in review


def test_phase11_h13_review_records_complete_release_evidence() -> None:
    review = Path("docs/reviews/phase11_h13_release_readiness.md").read_text(encoding="utf-8")

    assert "APPROVED — Human checkpoint H13 completed on 2026-09-28" in review
    assert "Release recommendation: **approve the first release**" in review
    assert "Proposed tag: `v0.1.0`" in review
    assert "the user replied `approve release, create tag v0.1.0`" in review
    assert "Tag status: approved and created" in review
    assert "2026-09-25" in review and "2026-09-26" in review and "2026-09-28" in review
    assert "Registry accounting | Pass" in review
    assert "Duplicate behavior | Pass" in review
    assert "Role and location quality | Pass" in review
    assert "Seniority quality | Pass" in review
    assert "Uncertainty | Pass" in review
    assert "Failure visibility | Pass" in review
    assert "Operability | Pass" in review
    assert "Repository quality | Pass" in review
    assert "Quantbox Research" in review
    assert "NVIDIA and PayPal" in review
    assert "complete pytest suite: 478 passed" in review
    assert "clean Git status at the H13 handoff" in review
    assert "Phase 11 and the first release are complete" in review


def test_phase12_package_c_cohort2_records_activation_and_failed_closed_evidence() -> None:
    review = Path("docs/reviews/phase12_package_c_cohort2_validation.md").read_text(
        encoding="utf-8"
    )

    assert "3 deterministic custom sources activated; 1 candidate failed closed" in review
    assert "Stripe, ServiceNow, and Coupang" in review
    assert "Flipkart remains disabled" in review
    assert "`pageup_xml_feed`" in review
    assert "`stripe_careers_index`" in review
    assert "percent-encoded Korean Coupang slug" in review
    assert "unapproved redirect regression" in review
    assert "119 enabled and 211 disabled" in review
    assert "205 remaining `search_only`" in review
    assert "37,260 jobs across 929 pages" in review
    assert "115 sources\nsucceeded, three were verified empty, and one was suspicious" in review
    assert "no failed, blocked, or\npartial sources" in review
    assert "535 passed" in review
    assert "`1c58608`" in review
    assert "`f667fc6`" in review
    assert "Packages D and E still require explicit approval" in review


def test_phase12_package_c_cohort3_records_official_source_replacements() -> None:
    review = Path("docs/reviews/phase12_package_c_cohort3_validation.md").read_text(
        encoding="utf-8"
    )

    assert "2 official deterministic sources activated" in review
    assert "D. E. Shaw India and Squarepoint Capital" in review
    assert "separate 407-job\ninternal collection" in review
    assert "`deshaw_india_index`" in review
    assert "board token `squarepointcapital`" in review
    assert "78 jobs, 1 page, 1 attempt" in review
    assert "88 jobs, 1 page, 1 attempt" in review
    assert "121 enabled and 209 disabled" in review
    assert "203 remaining `search_only`" in review
    assert "Workday's\npublic board changed during the run" in review
    assert "117 successful, three verified empty, one suspicious" in review
    assert "37,434 jobs across 932 pages" in review
    assert "541 passed" in review
    assert "`4066604`" in review
    assert "`224052a`" in review
    assert "Packages D and E still require explicit approval" in review


def test_phase12_package_c_cohort5_records_activation_and_fail_closed_evidence() -> None:
    review = Path("docs/reviews/phase12_package_c_cohort5_validation.md").read_text(
        encoding="utf-8"
    )

    assert "4 official deterministic sources activated; 1 candidate failed closed" in review
    assert "Atlassian, GitLab, Qure.ai, and Airbnb" in review
    assert "LinkedIn remains disabled and `search_only`" in review
    assert "`atlassian_careers_inventory`" in review
    assert "`qure_zoho_embedded`" in review
    assert "`airbnb_careers_pages`" in review
    assert "129 enabled and 201 disabled" in review
    assert "195 remaining `search_only`" in review
    assert "38,071 jobs across 947 pages" in review
    assert "125 successful, three verified empty, one known suspicious source" in review
    assert "216 jobs across 22 pages" in review
    assert "563 passed" in review
    assert "`d2ff2c1`" in review
    assert "`2674ebb`" in review
    assert "Packages D and E still require explicit approval" in review


def test_phase12_package_c_cohort6_records_activation_and_sweep_anomalies() -> None:
    review = Path("docs/reviews/phase12_package_c_cohort6_validation.md").read_text(
        encoding="utf-8"
    )

    assert "6 official deterministic sources activated; 1 candidate failed closed" in review
    assert "Intuit, Twilio, Roku, Meesho, PhonePe, Swiggy, and Tower Research Capital" in review
    assert "Roku remains disabled" in review
    assert "135 enabled and 195 disabled" in review
    assert "38,117 jobs across 986 pages" in review
    assert (
        "130 succeeded, three returned their verified empty state, and two were suspicious"
        in review
    )
    assert "Coupang's public PageUp feed" in review
    assert "574 passed" in review
    assert "Packages D and E on\n2026-09-29" in review


def test_phase12_package_c_cohort7_records_eight_deterministic_activations() -> None:
    review = Path("docs/reviews/phase12_package_c_cohort7_validation.md").read_text(
        encoding="utf-8"
    )

    assert "8 official deterministic sources activated" in review
    assert "Salesforce, Moloco," in review
    assert "InMobi, Postman, TrueFoundry, Booking.com, Navi, and Quadeye" in review
    assert "`booking_jibe_inventory`" in review
    assert "`navi_public_careers_api`" in review
    assert "`quadeye_zoho_proxy`" in review
    assert "1,865 jobs across 94 pages" in review
    assert "143 enabled and 187 disabled" in review
    assert "181 remaining `search_only`" in review
    assert "584 tests" in review


def test_phase12_package_c_cohort8_records_shared_host_pcsx_activation() -> None:
    review = Path("docs/reviews/phase12_package_c_cohort8_validation.md").read_text(
        encoding="utf-8"
    )

    assert "public PCSx careers surface" in review
    assert "59 unique jobs, six pages" in review
    assert "One listing has no location" in review
    assert "unknown-basis evidence" in review
    assert "Pagination stops only" in review
    assert "Eightfold AI is enabled" in review


def test_phase12_package_c_cohort9_records_index_exchange_activation() -> None:
    review = Path("docs/reviews/phase12_package_c_cohort9_validation.md").read_text(
        encoding="utf-8"
    )

    assert "30 declared table rows and 29 unique jobs" in review
    assert "Three current jobs are in Bengaluru" in review
    assert "270 unique jobs across 14 Workday pages" in review
    assert "Multi-location collapse" in review
    assert "No API credential" in review
    assert "Index Exchange is enabled" in review
    assert "S&P Global is enabled" in review


def test_phase12_package_c_cohort10_records_adobe_and_oracle_activation() -> None:
    review = Path("docs/reviews/phase12_package_c_cohort10_validation.md").read_text(
        encoding="utf-8"
    )

    assert "557 unique jobs across 28" in review
    assert "2,204 unique jobs across 12" in review
    assert "Two short nonterminal pages" in review
    assert "Browser automation was discovery" in review
    assert "Adobe and Oracle / OCI are enabled" in review


def test_phase12_cohort12_and_comprehensive_audit_are_reconciled() -> None:
    cohort = Path("docs/reviews/phase12_package_c_cohort12_validation.md").read_text(
        encoding="utf-8"
    )
    audit = Path("docs/reviews/phase12_comprehensive_code_and_coverage_audit.md").read_text(
        encoding="utf-8"
    )

    assert "Confluent is activated through its current public Ashby board" in cohort
    assert "18 complete jobs" in cohort
    assert "other disabled P1 companies" in cohort
    assert "150 enabled deterministic sources" in audit
    assert "174 disabled `search_only` sources" in audit
    assert "44,260 jobs across 1,146 pages" in audit
    assert "146 success, three valid empty, one reviewed suspicious" in audit
    assert "617 passing tests" in audit


def test_phase12_package_c_cohort11_records_american_express_activation() -> None:
    review = Path("docs/reviews/phase12_package_c_cohort11_validation.md").read_text(
        encoding="utf-8"
    )

    assert "507 unique jobs across three" in review
    assert "3,415, 3,410" in review
    assert "Browser automation was discovery" in review
    assert "American Express is enabled" in review
