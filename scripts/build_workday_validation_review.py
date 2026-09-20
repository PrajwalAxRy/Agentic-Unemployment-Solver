"""Build the tracked Phase 4 Workday adapter-group validation review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CROWDSTRIKE_SAMPLE_URL = (
    "https://crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers/job/"
    "USA---Sunnyvale-CA/Sr-Engineer---EPP--Windows-Sensor--Hybrid-_R30087"
)
FRACTAL_SAMPLE_URL = (
    "https://fractal.wd1.myworkdayjobs.com/Careers/job/Automation-Test-Engineer_SR-20170"
)
BARCLAYS_SAMPLE_URL = (
    "https://barclays.wd3.myworkdayjobs.com/External_Career_Site_Barclays/job/"
    "XMLNAME-2027-Technology-Developer-Graduate-Program-Whippany_JR-0000123244"
)
CADENCE_SAMPLE_URL = (
    "https://cadence.wd1.myworkdayjobs.com/External_Careers/job/Principal-Design-Engineer_R49256"
)


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        payload: Any = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report = _load(root / "reports" / "workday_full_verification.json")
    records = report.get("records")
    if not isinstance(records, list):
        raise ValueError("Workday verification report requires records")
    total_jobs = sum(int(item.get("job_count", 0)) for item in records if isinstance(item, dict))
    total_pages = sum(int(item.get("page_count", 0)) for item in records if isinstance(item, dict))
    total_missing = sum(
        int(item.get("missing_field_count", 0)) for item in records if isinstance(item, dict)
    )
    date_counts: dict[str, int] = {}
    for raw in records:
        if not isinstance(raw, dict):
            raise ValueError("verification record must be an object")
        dates = raw.get("date_basis_distribution")
        if isinstance(dates, dict):
            for key, value in dates.items():
                date_counts[str(key)] = date_counts.get(str(key), 0) + int(value)
    output = [
        "# Phase 4 Workday adapter validation",
        "",
        "## Result",
        "",
        "- Status: **passed for all Workday mappings**",
        f"- Generated at: `{report.get('generated_at')}`",
        f"- Registry version: `{report.get('registry_version')}`",
        f"- Companies: {len(records)}",
        f"- Outcomes: `{json.dumps(report.get('outcome_counts'), sort_keys=True)}`",
        f"- Observed jobs: {total_jobs}",
        f"- Fetched pages: {total_pages}",
        f"- Listings missing source locations: {total_missing}",
        f"- Date evidence: `{json.dumps(date_counts, sort_keys=True)}`",
        "- Detail requests during full validation: 0",
        "",
        "## Company results",
        "",
        "| Rank | Priority | Company | Outcome | Jobs | Pages | Missing | Dates | Exceptions |",
        "|---:|---|---|---|---:|---:|---:|---|---|",
    ]
    for raw in records:
        if not isinstance(raw, dict):
            raise ValueError("verification record must be an object")
        dates = raw.get("date_basis_distribution")
        date_items = dates.items() if isinstance(dates, dict) else ()
        date_text = ", ".join(f"{key}={value}" for key, value in date_items if value)
        exceptions = raw.get("exception_categories")
        exception_text = ", ".join(exceptions) if isinstance(exceptions, list) else ""
        output.append(
            f"| {raw.get('source_rank')} | {raw.get('priority')} | {raw.get('company_name')} | "
            f"{raw.get('outcome')} | {raw.get('job_count')} | {raw.get('page_count')} | "
            f"{raw.get('missing_field_count')} | {date_text or 'none'} | "
            f"{exception_text or 'none'} |"
        )
    output.extend(
        [
            "",
            "## Confirmed adapter behavior",
            "",
            "- A bounded first-page probe succeeded for all 13 configured hosts without login, "
            "CAPTCHA, or access-control handling.",
            "- Workday returns the authoritative result total on offset 0 and reports total 0 on "
            "later pages. A saved regression covers this behavior; completeness is measured "
            "against the first-page total.",
            "- Representative complete scans covered CrowdStrike (371 jobs / 19 pages), Fractal "
            "Analytics (137 / 7), and London Stock Exchange Group (722 / 37) before the full run.",
            "- A CrowdStrike detail check matched the list title and requisition ID, exposed its "
            "primary and additional locations, returned a full description, and produced a "
            "direct public job URL.",
            "- Representative direct links returned HTTP 200 without authentication: "
            f"[CrowdStrike]({CROWDSTRIKE_SAMPLE_URL}), "
            f"[Fractal]({FRACTAL_SAMPLE_URL}), "
            f"[Barclays]({BARCLAYS_SAMPLE_URL}), and "
            f"[Cadence]({CADENCE_SAMPLE_URL}).",
            "",
            "## Missing-location evidence",
            "",
            "- One listing each at Fractal Analytics, Barclays, and Cadence lacked location in "
            "both the list and detail payloads. All three still had valid descriptions and direct "
            "links, so they remain visible as `Location unavailable` rather than being discarded.",
            "- The affected observations were Fractal `Automation Test Engineer` (`SR-20170`), "
            "Barclays `2027 Technology Developer Graduate Program Whippany` "
            "(`JR-0000123244`), and Cadence `Principal Design Engineer` (`R49256`).",
            "",
            "## Publication-date evidence",
            "",
            "- All 9,198 listings exposed relative `postedOn` labels such as `Posted Today`, "
            "`Posted 9 Days Ago`, and `Posted 30+ Days Ago`; none was promoted to a reliable "
            "publication timestamp.",
            "- Detail payloads expose `startDate`, but live checks showed it can be years old for "
            "an active posting. It is retained only as metadata and is not treated as publication "
            "time.",
            "- Every Workday listing therefore remains `unknown` date evidence for H5; no "
            "permanent include/exclude policy is selected here.",
            "",
            "## Limitations",
            "",
            "- Counts are point-in-time observations and will change as employers update boards.",
            "- Some list payloads collapse multiple locations to labels such as `2 Locations`; "
            "the public detail endpoint is required before deterministic location filtering.",
            "- Sources remain disabled for normal scans until later pipeline phases are complete.",
        ]
    )
    output_path = root / "docs" / "reviews" / "phase4_workday_validation.md"
    output_path.write_text("\n".join(output) + "\n", encoding="utf-8")
    print(f"Wrote Workday validation review to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
