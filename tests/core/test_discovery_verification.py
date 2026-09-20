"""Tests for applying sanitized source-probe evidence."""

from job_finder.core.discovery_verification import apply_verification_results


def proposal(adapter: str = "greenhouse") -> dict[str, object]:
    return {
        "company_id": "example",
        "status": "proposed",
        "adapter_type": adapter,
        "confidence": "high" if adapter != "search_only" else "medium",
        "official_careers_url": "https://jobs.example.com",
        "list_endpoint": "https://api.example.com/jobs",
        "adapter_parameters": {},
        "evidence": [],
        "access_concern": None,
    }


def verification(probe: dict[str, object]) -> dict[str, object]:
    return {"results": [{"company_id": "example", "probes": [probe]}]}


def probe(outcome: str, *, final_url: str = "https://api.example.com/jobs") -> dict[str, object]:
    return {
        "requested_url": "https://api.example.com/jobs",
        "final_url": final_url,
        "outcome": outcome,
        "status_code": 200,
        "detail": "probe detail",
        "job_count": 3,
    }


def test_successful_structured_probe_becomes_auto_verified_but_not_enabled() -> None:
    revised = apply_verification_results(
        {"proposals": [proposal()]},
        verification(probe("success")),
    )
    result = revised["proposals"][0]

    assert result["status"] == "auto_verified"
    assert "enabled" not in result
    assert result["evidence"][0]["evidence_type"] == "structured_list_probe"


def test_access_control_remains_visible() -> None:
    item = proposal("search_only")
    item["list_endpoint"] = item["official_careers_url"]
    access_probe = probe("access_block", final_url="https://jobs.example.com")
    access_probe["requested_url"] = "https://jobs.example.com"

    result = apply_verification_results(
        {"proposals": [item]},
        verification(access_probe),
    )["proposals"][0]

    assert result["status"] == "access_concern"
    assert result["confidence"] == "low"
    assert result["access_concern"] is not None


def test_successful_reprobe_clears_stale_access_concern() -> None:
    item = proposal("search_only")
    item["status"] = "access_concern"
    item["access_concern"] = "Earlier probe matched dormant CAPTCHA configuration."
    item["list_endpoint"] = item["official_careers_url"]
    successful_probe = probe("success", final_url="https://jobs.example.com")
    successful_probe["requested_url"] = "https://jobs.example.com"

    result = apply_verification_results(
        {"proposals": [item]},
        verification(successful_probe),
    )["proposals"][0]

    assert result["status"] == "auto_verified"
    assert result["access_concern"] is None


def test_workday_redirect_updates_adapter_parameters() -> None:
    item = proposal("search_only")
    item["list_endpoint"] = item["official_careers_url"]
    workday_probe = probe(
        "invalid_content",
        final_url="https://fractal.wd1.myworkdayjobs.com/Careers",
    )
    workday_probe["requested_url"] = "https://jobs.example.com"

    result = apply_verification_results(
        {"proposals": [item]},
        verification(workday_probe),
    )["proposals"][0]

    assert result["status"] == "auto_verified"
    assert result["adapter_type"] == "workday"
    assert result["adapter_parameters"] == {
        "host": "fractal.wd1.myworkdayjobs.com",
        "tenant": "fractal",
        "site": "Careers",
    }


def test_workday_redirect_skips_locale_to_find_site() -> None:
    item = proposal("search_only")
    item["list_endpoint"] = item["official_careers_url"]
    workday_probe = probe(
        "invalid_content",
        final_url=(
            "https://crowdstrike.wd5.myworkdayjobs.com/en-US/crowdstrikecareers/job/India/Role_R1"
        ),
    )
    workday_probe["requested_url"] = "https://jobs.example.com"

    result = apply_verification_results(
        {"proposals": [item]},
        verification(workday_probe),
    )["proposals"][0]

    assert result["adapter_parameters"] == {
        "host": "crowdstrike.wd5.myworkdayjobs.com",
        "tenant": "crowdstrike",
        "site": "crowdstrikecareers",
    }
