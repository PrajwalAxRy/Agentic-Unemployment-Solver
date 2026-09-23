"""Human-readable Markdown output for a completed manual scan."""

from __future__ import annotations

from pathlib import Path

from job_finder.scan import (
    CompanyAccountingRecord,
    MatchingJobRecord,
    ReviewCandidateRecord,
    ScanOutcome,
    ScanReport,
)


def render_scan_markdown(report: ScanReport) -> str:
    """Render one scan with matches first and coverage stated unambiguously."""
    lines = [
        "# Job Finder scan report",
        "",
        _outcome_message(report),
        "",
        "## New matching jobs",
        "",
        *_matching_table(report.matching_jobs),
        "",
        "## Date-uncertain matching candidates",
        "",
        "These jobs passed role, India-location, and seniority checks, but their publication date "
        "is not verified. They are not part of the strict ten-day result.",
        "",
        *_matching_table(report.date_uncertain_jobs),
        "",
        "## Candidates requiring review",
        "",
        *_review_table(report.review_candidates),
        "",
        "## Coverage and run summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Run outcome | {_markdown(report.outcome.value)} |",
        f"| Canonical companies accounted for | {report.metrics.canonical_company_count} |",
        f"| Enabled / attempted companies | {report.metrics.enabled_company_count} / "
        f"{report.metrics.attempted_company_count} |",
        f"| Successful / valid-empty / failed sources | "
        f"{report.metrics.successful_company_count} / "
        f"{report.metrics.valid_empty_company_count} / {report.metrics.failed_company_count} |",
        f"| Disabled or deferred companies | {report.metrics.disabled_company_count} |",
        f"| Listings observed | {report.metrics.listing_count:,} |",
        f"| Recency / role / retained candidates | "
        f"{report.metrics.recency_candidate_count:,} / "
        f"{report.metrics.role_candidate_count:,} / "
        f"{report.metrics.retained_candidate_count:,} |",
        f"| New identities / duplicates suppressed | {report.metrics.new_identity_count} / "
        f"{report.metrics.duplicate_suppressed_count} |",
        f"| New strict matches / date-uncertain matches / review candidates | "
        f"{len(report.matching_jobs)} / {len(report.date_uncertain_jobs)} / "
        f"{len(report.review_candidates)} |",
        f"| Duration | {report.duration_seconds:.3f} seconds |",
        "",
        f"Registry `{report.registry_version}`; profile `{report.profile_version}` "
        f"(`{report.profile_hash}`); prompt `{report.prompt_version}`; model policy "
        f"`{report.model_policy}`.",
        "",
        "## Source failures",
        "",
        *_source_failure_table(report),
        "",
        "## Unsupported and blocked sources",
        "",
        *_exception_table(report.company_accounting),
        "",
        "## LLM usage",
        "",
        f"Requests: {report.usage.request_count}; measured input tokens: "
        f"{report.usage.measured_input_tokens:,}; measured output tokens: "
        f"{report.usage.measured_output_tokens:,}.",
        "",
        f"Run ID: `{report.run_id}`. Started `{report.started_at}`; completed "
        f"`{report.completed_at}`.",
        "",
    ]
    return "\n".join(lines)


def write_scan_markdown(report: ScanReport, path: Path) -> None:
    """Write a human-readable report to a local generated path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_scan_markdown(report), encoding="utf-8")


def _outcome_message(report: ScanReport) -> str:
    new_matches = len(report.matching_jobs) + len(report.date_uncertain_jobs)
    if report.outcome is ScanOutcome.COMPLETE:
        if new_matches:
            return (
                f"**Scan completed with complete enabled-source coverage and {new_matches} new "
                "matching job(s).**"
            )
        return "**Scan completed with complete enabled-source coverage. No new matching jobs.**"
    if report.outcome is ScanOutcome.PARTIAL:
        return (
            "**Coverage is incomplete. Results from healthy sources are shown, and every failed "
            "source is listed below.**"
        )
    return "**Scan failed because no enabled source completed successfully.**"


def _matching_table(items: tuple[MatchingJobRecord, ...]) -> list[str]:
    if not items:
        return ["No new matching jobs in this section."]
    lines = [
        "| Company | Job | Location | Date (basis) | First seen | Seniority evidence | Link |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in items:
        source_date = item.publication_date or item.raw_date_text or "Unavailable"
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown(item.company_name),
                    _markdown(item.title),
                    _markdown(item.location),
                    f"{_markdown(source_date)} ({item.date_basis})",
                    _markdown(item.first_seen_at),
                    _markdown(item.seniority_evidence),
                    f"[open job]({item.canonical_url})",
                )
            )
            + " |"
        )
    return lines


def _review_table(items: tuple[ReviewCandidateRecord, ...]) -> list[str]:
    if not items:
        return ["No candidates require manual review."]
    lines = [
        "| Company | Job | Location | Review category | Reason / evidence | Date lane | Link |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in items:
        explanation = item.reason
        if item.evidence:
            explanation = f"{explanation} Evidence: {item.evidence}"
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown(item.company_name),
                    _markdown(item.title),
                    _markdown(item.location),
                    _markdown(item.category),
                    _markdown(explanation),
                    _markdown(item.candidate_section),
                    f"[open job]({item.canonical_url})",
                )
            )
            + " |"
        )
    return lines


def _source_failure_table(report: ScanReport) -> list[str]:
    if not report.source_failures:
        return ["No enabled source failed."]
    lines = [
        "| Company | Adapter | Outcome | Diagnostic categories |",
        "|---|---|---|---|",
    ]
    for item in report.source_failures:
        lines.append(
            f"| {_markdown(item.company_name)} | {item.adapter_type} | {item.outcome} | "
            f"{_markdown(', '.join(item.exception_categories) or 'unspecified')} |"
        )
    return lines


def _exception_table(accounting: tuple[CompanyAccountingRecord, ...]) -> list[str]:
    exceptions = tuple(item for item in accounting if item.status in {"blocked", "unsupported"})
    if not exceptions:
        return [
            "No company is marked blocked or unsupported. Disabled/custom-adapter backlog entries "
            "remain fully enumerated in the machine-readable JSON report."
        ]
    lines = [
        "| Company | Status | Reason |",
        "|---|---|---|",
    ]
    for item in exceptions:
        lines.append(
            f"| {_markdown(item.company_name)} | {item.status} | "
            f"{_markdown(item.exception_reason or 'No reason recorded')} |"
        )
    lines.append("")
    lines.append(
        "Disabled and custom-adapter backlog entries remain fully enumerated in the "
        "machine-readable JSON report."
    )
    return lines


def _markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()
