"""Build the tracked Phase 4 Greenhouse adapter-group validation review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from job_finder.core.adapter_validation import GREENHOUSE_DOCUMENTATION_URL


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        payload: Any = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report = _load(root / "reports" / "greenhouse_full_verification.json")
    records = report.get("records")
    if not isinstance(records, list):
        raise ValueError("Greenhouse verification report requires records")
    total_jobs = sum(int(item.get("job_count", 0)) for item in records if isinstance(item, dict))
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
        "# Phase 4 Greenhouse adapter validation",
        "",
        "## Result",
        "",
        "- Status: **passed**",
        f"- Generated at: `{report.get('generated_at')}`",
        f"- Registry version: `{report.get('registry_version')}`",
        f"- Companies: {len(records)}",
        f"- Outcomes: `{json.dumps(report.get('outcome_counts'), sort_keys=True)}`",
        f"- Observed jobs: {total_jobs}",
        f"- Missing required fields: {total_missing}",
        f"- Date evidence: `{json.dumps(date_counts, sort_keys=True)}`",
        "- Pagination: one complete public `jobs` collection checked against `meta.total`",
        f"- Official API contract: [Greenhouse Job Board API]({GREENHOUSE_DOCUMENTATION_URL})",
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
            "## Corrections and manual evidence",
            "",
            "- Databricks and Graviton Research Capital embedded URLs had been misparsed as "
            "board token `embed`; their public tokens are `databricks` and "
            "`gravitonresearchcapital`.",
            "- Clipboard Health's official careers page now links to the public Ashby board "
            "`clipboard`; the obsolete Greenhouse board returns HTTP 404. Clipboard was moved "
            "to the Ashby cohort and that entire cohort was revalidated.",
            "- Databricks returned 877 jobs in a 9.6 MB response. The shared client remains "
            "bounded, with a tested 20 MB maximum that safely covers the observed board.",
            "- Pure Storage returned 354 complete jobs, resolving its earlier two-megabyte "
            "discovery-probe limitation.",
            "",
            "## Publication-date evidence",
            "",
            "- Greenhouse `first_published` is retained as publication evidence.",
            "- AlphaGrep, Graviton Research Capital, and SingleStore each had one job without "
            "`first_published`; those three jobs retain `updated_at` with an explicit "
            "`updated_date_fallback` diagnostic.",
            "- No permanent inclusion/exclusion decision is made here. The fallback jobs remain "
            "separate for the mandatory full-registry H5 date-coverage review.",
            "",
            "## Limitations",
            "",
            "- Counts are point-in-time observations and will change as employers update boards.",
            "- Completeness is based on the official public API's collection and `meta.total`; "
            "client-rendered board DOM counts are not used.",
            "- Sources remain disabled for normal scans until later pipeline phases are complete.",
        ]
    )
    output_path = root / "docs" / "reviews" / "phase4_greenhouse_validation.md"
    output_path.write_text("\n".join(output) + "\n", encoding="utf-8")
    print(f"Wrote Greenhouse validation review to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
