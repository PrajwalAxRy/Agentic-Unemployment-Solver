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
    assert "Ashby is recommended first" in review
    assert "Canonical scope: 330 of 330 companies" in review
