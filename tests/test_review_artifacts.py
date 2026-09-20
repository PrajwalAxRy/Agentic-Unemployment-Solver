"""Checks that mandatory human-checkpoint artifacts match tracked inventory."""

from pathlib import Path


def test_h2_review_artifact_has_required_decision_sections_and_counts() -> None:
    review = Path("docs/reviews/h2_source_inventory_review.md").read_text(encoding="utf-8")

    assert "STOP — awaiting human decision" in review
    assert "216 read-only verified sources" in review
    assert "44 access-concern sources" in review
    assert "68 conflicting or non-enumerating sources" in review
    assert "2 responsive but oversized structured boards" in review
    assert "Access-policy concerns requiring approval" in review
    assert "Conflicting or non-enumerating proposals requiring inspection" in review
    assert "Verified search-only sources requiring custom adapters" in review
    assert "Ashby is recommended first" in review
    assert "Canonical scope: 330 of 330 companies" in review
