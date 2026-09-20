"""Tests for hosted ATS HTML fingerprinting and guarded application."""

from job_finder.core.source_fingerprint import (
    apply_fingerprint_results,
    fingerprint_html,
)


def test_fingerprint_html_detects_supported_embedded_boards() -> None:
    fingerprints = fingerprint_html(
        '<a href="https://jobs.lever.co/example">Jobs</a>'
        '<script src="https:\\/\\/jobs.ashbyhq.com\\/other"></script>'
    )

    assert {item.adapter_type for item in fingerprints} == {"lever", "ashby"}


def test_fingerprint_html_extracts_enterprise_ats_parameters() -> None:
    fingerprints = fingerprint_html(
        '<a href="https://company.eightfold.ai/careers">Jobs</a>'
        '<a href="https://tenant.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/'
        'en/sites/CX_1/jobs">Oracle jobs</a>'
    )

    by_adapter = {item.adapter_type: item for item in fingerprints}
    assert by_adapter["eightfold"].adapter_parameters == {"tenant": "company"}
    assert by_adapter["oracle_cloud"].adapter_parameters == {"site_number": "CX_1"}


def test_fingerprint_normalizes_legacy_greenhouse_and_ignores_shared_assets() -> None:
    fingerprints = fingerprint_html(
        '<script src="https://boards.greenhouse.io/embed/job_board/js?for=example"></script>'
        '<script src="https://jobs.jobvite.com/__assets__/careers.js"></script>'
        '<a href="https://app.eightfold.ai/careers?domain=example.com">Shared</a>'
        '<a href="https:\\/\\/jobs.ashbyhq.com\\/example\\">Jobs</a>'
    )

    by_adapter = {item.adapter_type: item for item in fingerprints}
    assert set(by_adapter) == {"greenhouse", "ashby"}
    assert by_adapter["greenhouse"].adapter_parameters == {"board_token": "example"}
    assert by_adapter["ashby"].adapter_parameters == {"board_name": "example"}


def test_unambiguous_fingerprint_updates_adapter_without_enabling() -> None:
    proposals: dict[str, object] = {
        "proposals": [
            {
                "company_id": "example",
                "status": "auto_verified",
                "adapter_type": "search_only",
                "adapter_parameters": {"search_url": "https://example.com/careers"},
                "evidence": [],
            }
        ]
    }
    results = {
        "results": [
            {
                "company_id": "example",
                "outcome": "matched",
                "fingerprints": [
                    {
                        "adapter_type": "lever",
                        "adapter_parameters": {"site": "example"},
                        "source_url": "https://jobs.lever.co/example",
                        "list_endpoint": "https://api.lever.co/v0/postings/example?mode=json",
                        "listing_mode": "complete_list",
                    }
                ],
            }
        ]
    }

    revised = apply_fingerprint_results(proposals, results)
    source = revised["proposals"]
    assert isinstance(source, list)
    assert source[0]["adapter_type"] == "lever"
    assert source[0]["status"] == "auto_verified"
    assert "enabled" not in source[0]


def test_ambiguous_fingerprints_remain_search_only() -> None:
    proposals: dict[str, object] = {
        "proposals": [
            {
                "company_id": "example",
                "adapter_type": "search_only",
                "notes": "",
                "evidence": [],
            }
        ]
    }
    fingerprint = {
        "adapter_parameters": {"site": "example"},
        "source_url": "https://jobs.lever.co/example",
        "list_endpoint": "https://api.lever.co/v0/postings/example?mode=json",
        "listing_mode": "complete_list",
    }
    results = {
        "results": [
            {
                "company_id": "example",
                "outcome": "matched",
                "fingerprints": [
                    {"adapter_type": "lever", **fingerprint},
                    {"adapter_type": "jobvite", **fingerprint},
                ],
            }
        ]
    }

    revised = apply_fingerprint_results(proposals, results)
    source = revised["proposals"]
    assert isinstance(source, list)
    assert source[0]["adapter_type"] == "search_only"
    assert "Multiple hosted ATS" in source[0]["notes"]
