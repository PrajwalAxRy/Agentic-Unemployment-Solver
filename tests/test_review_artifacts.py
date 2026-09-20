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
    assert "Ashby, Greenhouse, and Lever have now passed full adapter-group validation" in review
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
