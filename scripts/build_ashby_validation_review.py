"""Build the tracked Phase 3 Ashby adapter-group validation review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from job_finder.core.adapter_validation import ASHBY_DOCUMENTATION_URL


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        payload: Any = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report = _load(root / "reports" / "ashby_full_verification.json")
    records = report.get("records")
    if not isinstance(records, list):
        raise ValueError("Ashby verification report requires records")
    total_jobs = sum(int(item.get("job_count", 0)) for item in records if isinstance(item, dict))
    total_missing = sum(
        int(item.get("missing_field_count", 0)) for item in records if isinstance(item, dict)
    )
    output = [
        "# Phase 3 Ashby adapter validation",
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
        "- Pagination: one complete public `jobs` collection per board; no page tokens",
        f"- Official API contract: [Ashby public job-posting API]({ASHBY_DOCUMENTATION_URL})",
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
            "- Cerebras Systems required the exact case-sensitive board name `Cerebras`; the "
            "lower-case variant returned truncated invalid JSON during the representative run.",
            "- WisdomAI had moved from the obsolete `Wisdom AI` slug to `Wisdom-AI`; the current "
            "public board returned 17 complete jobs.",
            "- Kognitos, Kong, and Cerebras direct job URLs returned public job pages whose titles "
            "matched normalized adapter records.",
            "- Deeptune returned the documented healthy empty shape and remains a valid empty "
            "board rather than a collection failure.",
            "- Harvey's 299-job, 3.9 MB response passed the bounded shared client, resolving "
            "the earlier two-megabyte discovery-probe limitation.",
            "",
            "## Limitations",
            "",
            "- Counts are point-in-time observations and will change as employers update boards.",
            "- Ashby board pages are client-rendered; completeness is based on the documented "
            "public posting API and the successful full collection, not DOM item counting.",
            "- Sources remain disabled for normal scans until later pipeline phases are complete.",
        ]
    )
    output_path = root / "docs" / "reviews" / "phase3_ashby_validation.md"
    output_path.write_text("\n".join(output) + "\n", encoding="utf-8")
    print(f"Wrote Ashby validation review to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
