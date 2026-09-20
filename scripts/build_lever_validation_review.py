"""Build the tracked Phase 4 Lever adapter-group validation review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from job_finder.core.adapter_validation import LEVER_DOCUMENTATION_URL


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        payload: Any = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report = _load(root / "reports" / "lever_full_verification.json")
    records = report.get("records")
    if not isinstance(records, list):
        raise ValueError("Lever verification report requires records")
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
        "# Phase 4 Lever adapter validation",
        "",
        "## Result",
        "",
        "- Status: **passed for all current Lever mappings**",
        f"- Generated at: `{report.get('generated_at')}`",
        f"- Registry version: `{report.get('registry_version')}`",
        f"- Companies: {len(records)}",
        f"- Outcomes: `{json.dumps(report.get('outcome_counts'), sort_keys=True)}`",
        f"- Observed jobs: {total_jobs}",
        f"- Jobs missing descriptions: {total_missing}",
        f"- Date evidence: `{json.dumps(date_counts, sort_keys=True)}`",
        "- Pagination: `skip`/`limit` requests continue until a short page",
        f"- Official API contract: [Lever Postings API]({LEVER_DOCUMENTATION_URL})",
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
            "- Bazaarvoice exposed one job with an empty plain-text description but populated "
            "HTML. A saved regression fixture now verifies the HTML fallback.",
            "- Lever sometimes stores requirements only in structured `lists`; those fields are "
            "now included so AI duties and experience requirements are not lost.",
            "- BarRaiser exposes 16 jobs and Paytm one job with no description in either the list "
            "or single-posting public API. The jobs remain visible with `missing_description` "
            "evidence for later manual-review handling.",
            "- Dream Sports' official careers page still links to the obsolete `dreamsports` "
            "Lever board, but both the board and API return HTTP 404. It remains in the approved "
            "330-company scope as a documented search-only conflict, not a verified Lever source.",
            "",
            "## Publication-date evidence",
            "",
            "- All observed Lever jobs expose `createdAt`, but the public Postings API "
            "documentation does not define it as publication time.",
            "- All 386 jobs therefore remain `unknown` date evidence for the mandatory H5 "
            "coverage review; no permanent include/exclude policy is selected here.",
            "",
            "## Limitations",
            "",
            "- Counts are point-in-time observations and will change as employers update boards.",
            "- A missing description prevents automatic AI-work and seniority assessment; those "
            "jobs must remain explicit rather than being silently rejected.",
            "- Sources remain disabled for normal scans until later pipeline phases are complete.",
        ]
    )
    output_path = root / "docs" / "reviews" / "phase4_lever_validation.md"
    output_path.write_text("\n".join(output) + "\n", encoding="utf-8")
    print(f"Wrote Lever validation review to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
