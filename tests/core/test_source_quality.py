"""Tests for explicit source-quality corrections."""

from job_finder.core.source_quality import apply_quality_corrections


def proposal(company_id: str) -> dict[str, object]:
    return {
        "company_id": company_id,
        "status": "auto_verified",
        "official_careers_url": "https://wrong.example/careers",
        "confidence": "medium",
        "evidence": [],
        "access_concern": None,
        "notes": "",
    }


def test_replacement_returns_source_to_probe_ready_state() -> None:
    payload: dict[str, object] = {"proposals": [proposal("example")]}
    corrections = {
        "replacements": [
            {
                "company_id": "example",
                "url": "https://jobs.ashbyhq.com/example",
                "title": "Example jobs",
                "reason": "Better direct ATS evidence.",
            }
        ],
        "downgrades": [],
    }

    revised = apply_quality_corrections(payload, corrections)
    proposals = revised["proposals"]
    assert isinstance(proposals, list)
    result = proposals[0]
    assert result["status"] == "proposed"
    assert result["adapter_type"] == "ashby"
    assert result["adapter_parameters"] == {"board_name": "example"}


def test_downgrade_cannot_remain_auto_verified() -> None:
    payload: dict[str, object] = {"proposals": [proposal("example")]}
    corrections = {
        "replacements": [],
        "downgrades": [
            {
                "company_id": "example",
                "reason": "Search hit is a third-party copy.",
            }
        ],
    }

    revised = apply_quality_corrections(payload, corrections)
    proposals = revised["proposals"]
    assert isinstance(proposals, list)
    result = proposals[0]
    assert result["status"] == "conflict"
    assert result["confidence"] == "low"
    assert result["access_concern"] == "Search hit is a third-party copy."


def test_matching_replacement_preserves_probe_outcome() -> None:
    item = proposal("example")
    item["official_careers_url"] = "https://example.com/careers"
    item["status"] = "access_concern"
    item["confidence"] = "low"
    item["access_concern"] = "Public page challenged the bounded probe."
    payload: dict[str, object] = {"proposals": [item]}
    corrections = {
        "replacements": [
            {
                "company_id": "example",
                "url": "https://example.com/careers",
                "title": "Example careers",
                "reason": "Correct source.",
            }
        ],
        "downgrades": [],
    }

    revised = apply_quality_corrections(payload, corrections)
    proposals = revised["proposals"]
    assert isinstance(proposals, list)
    result = proposals[0]
    assert result["status"] == "access_concern"
    assert result["access_concern"] == "Public page challenged the bounded probe."


def test_replacement_evidence_preserves_outcome_after_redirect() -> None:
    item = proposal("example")
    item["official_careers_url"] = "https://example.com/careers/search"
    item["evidence"] = [
        {
            "url": "https://example.com/jobs/search",
            "evidence_type": "quality_correction_candidate",
            "note": "Example jobs",
        }
    ]
    payload: dict[str, object] = {"proposals": [item]}
    corrections = {
        "replacements": [
            {
                "company_id": "example",
                "url": "https://example.com/jobs/search",
                "title": "Example jobs",
                "reason": "Correct source.",
            }
        ],
        "downgrades": [],
    }

    revised = apply_quality_corrections(payload, corrections)
    proposals = revised["proposals"]
    assert isinstance(proposals, list)
    result = proposals[0]
    assert result["status"] == "auto_verified"
