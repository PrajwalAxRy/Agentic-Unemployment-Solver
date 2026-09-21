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


def test_h5_review_records_full_registry_date_coverage_and_decision_request() -> None:
    review = Path("docs/reviews/h5_date_coverage_review.md").read_text(encoding="utf-8")

    assert "**STOP — Human checkpoint H5: awaiting the user's uncertain-date decision**" in review
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
    assert "Choose option 1, 2, 3, or 4" in review
