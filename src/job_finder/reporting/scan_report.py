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
    evaluation_status = (
        "deferred (discovery only)"
        if report.halt_reason == "discovery_only"
        else "complete"
        if report.evaluation_complete
        else "incomplete"
    )
    lines = [
        "# Job Finder scan report",
        "",
        _outcome_message(report),
        f"Evaluation: {evaluation_status}; "
        f"pending: {report.pending_count}."
        + (
            f" Resume with `job-finder evaluate` before midnight IST ending {report.batch_date}."
            if report.pending_count
            else ""
        ),
        "",
        "## How to answer the seven review questions",
        "",
        "| Question | Where to look | How to answer |",
        "|---|---|---|",
        "| Coverage status | The bold sentence above and **Coverage and run summary** | "
        "Report `complete`, `partial`, or `failed`. |",
        "| New strict matches | **Matching jobs (new and known)** | Use the identity column "
        "to select new jobs; known matches remain in the cumulative report. |",
        "| Matches with uncertain dates | **Date-uncertain matching candidates** | List its "
        "jobs separately; these are not strict ten-day results. |",
        "| Why a job is shown | Match tables: **Relevance**, **Why it is relevant**, "
        "**Seniority evidence** and **Why it matched**; review table: **Review category** and "
        "**Reason / evidence** | Use those cells, not the job title alone. Rows are ordered "
        "`core AI`, then `AI-involved` (AI is a real part of the job), then `uncertain` (AI is "
        "in the picture but it is unclear this person does it: check it). **What you'd do** "
        "is the model's one-sentence summary of the role. A `-` means the row predates "
        "relevance judging or ran under `--seniority-only`. |",
        "| Companies with source problems | **Source failures** | List those companies. "
        "**Unsupported and blocked sources** are known release limitations, not failures of this "
        "run. |",
        "| Full JSON results | The terminal's `Wrote machine-readable report to ...` line | "
        "The default is `reports/latest_scan.json`. |",
        "| State safety instructions | `docs/07_scan_runbook.md`, **State safety** | This section "
        "contains inspect, backup, restore, and guarded-reset guidance. |",
        "",
        "## Matching jobs (new and known)",
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
        f"Requests with unknown provider usage: {report.unknown_usage_request_count}. "
        "These may include interrupted paid calls.",
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
        f"| New / known identities | {report.metrics.new_identity_count} / "
        f"{report.metrics.duplicate_suppressed_count} |",
        f"| Strict matches / date-uncertain matches / review candidates | "
        f"{len(report.matching_jobs)} / {len(report.date_uncertain_jobs)} / "
        f"{len(report.review_candidates)} |",
        f"| Duration | {report.duration_seconds:.3f} seconds |",
        "",
        f"Report schema `{report.schema_version}`; registry `{report.registry_version}`; "
        f"profile `{report.profile_version}` "
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
    matches = report.matching_jobs + report.date_uncertain_jobs
    new_matches = sum(item.new_identity for item in matches)
    if report.outcome is ScanOutcome.COMPLETE:
        if not report.evaluation_complete:
            return "**Enabled-source coverage is complete. Evaluation is incomplete.**"
        if matches:
            return (
                f"**Scan completed with complete enabled-source coverage and {len(matches)} "
                f"matching job(s), including {new_matches} new.**"
            )
        return "**Scan completed with complete enabled-source coverage. No new matching jobs.**"
    if report.outcome is ScanOutcome.PARTIAL:
        return (
            "**Coverage is incomplete. Results from healthy sources are shown, and every failed "
            "source is listed below.**"
        )
    return "**Scan failed because no enabled source completed successfully.**"


# Display order and label per relevance value. 1.x strings (substantive, peripheral) are
# still stored on rows judged before prompt 2.0.0 and sort beside their nearest tier.
_RELEVANCE_DISPLAY: dict[str, tuple[int, str]] = {
    "core_ai": (0, "core AI"),
    "substantive": (0, "substantive"),
    "ai_involved": (1, "AI-involved"),
    "peripheral": (1, "peripheral"),
    "uncertain": (2, "uncertain"),
}


def _relevance_rank(item: MatchingJobRecord) -> int:
    return _RELEVANCE_DISPLAY.get(item.relevance or "", (3, ""))[0]


def _relevance_label(relevance: str | None) -> str:
    if relevance is None:
        return "-"
    return _RELEVANCE_DISPLAY.get(relevance, (3, relevance))[1]


def _matching_table(items: tuple[MatchingJobRecord, ...]) -> list[str]:
    if not items:
        return ["No new matching jobs in this section."]
    lines = [
        "| Company | Job | Location | Date (basis) | First seen | Relevance | What you'd do | "
        "Why it is relevant | Seniority evidence | Why it matched | Identity | Link |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    # Stable: within a tier the incoming order (newest first) is kept.
    for item in sorted(items, key=_relevance_rank):
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
                    # Dashes rather than blanks: a row judged before migration 5, or one
                    # produced under --seniority-only, has no relevance verdict at all.
                    # That is different from a verdict with nothing to say about it.
                    _markdown(_relevance_label(item.relevance)),
                    _markdown(item.work_summary or "-"),
                    _markdown(item.relevance_reason or "-"),
                    _markdown(item.seniority_evidence),
                    _markdown(item.seniority_reason),
                    "new" if item.new_identity else "known",
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
