"""Complete-registry recency, role, and location filter validation."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

from job_finder.adapters.base import AdapterRegistry, JobDetailAdapter, list_jobs_with_retry
from job_finder.adapters.http_client import HttpRequestError
from job_finder.core.company_registry import CompanySourceRegistry
from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.core.recency import RecencyDecision, assess_listing_recency
from job_finder.core.search_profile import SearchProfile
from job_finder.core.source_contracts import AdapterOutcome, AdapterResult, CompanySource
from job_finder.filters.locations import LocationDecision, LocationFilterResult, filter_job_location
from job_finder.filters.roles import RoleDecision, RoleFilterResult, filter_role
from job_finder.normalization.jobs import normalize_job


class CandidateSection(StrEnum):
    """User-visible recency section for a filter candidate."""

    STRICT = "strict_recent"
    UNCERTAIN = "uncertain_date"


class FinalFilterDecision(StrEnum):
    """Final pre-description outcome."""

    RETAINED = "retained"
    REVIEW = "review"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class FilterListingRecord:
    """Sanitized explainable decision for one recency-eligible listing."""

    company_id: str
    company_name: str
    source_rank: int
    adapter_type: str
    title_original: str
    location_original: str
    canonical_url: str
    candidate_section: CandidateSection
    date_basis: DateBasis
    raw_date_text: str | None
    role: RoleFilterResult
    location: LocationFilterResult | None
    final_decision: FinalFilterDecision
    normalized_job: NormalizedJob


@dataclass(frozen=True, slots=True)
class CompanyFilterRecord:
    """Per-company reduction counts and source health."""

    company_id: str
    company_name: str
    source_rank: int
    adapter_type: str
    outcome: str
    complete: bool
    attempt_count: int
    page_count: int
    listing_count: int
    strict_recent_count: int
    uncertain_candidate_count: int
    recency_excluded_count: int
    explicit_role_count: int
    conditional_role_count: int
    role_rejected_count: int
    location_pass_count: int
    location_review_count: int
    location_rejected_count: int
    retained_count: int
    review_count: int
    rejected_count: int
    exception_categories: tuple[str, ...]
    detail_fetch_count: int
    detail_failure_count: int


@dataclass(frozen=True, slots=True)
class FilterVerificationReport:
    """Complete Phase 6 filter reduction and sampling input."""

    schema_version: int
    generated_at: str
    scan_at: str
    boundary: str
    registry_version: str
    profile_id: str
    profile_version: str
    profile_hash: str
    enabled_company_count: int
    outcome_counts: Mapping[str, int]
    listing_count: int
    strict_recent_count: int
    uncertain_candidate_count: int
    recency_excluded_count: int
    role_counts: Mapping[str, int]
    role_rejection_reasons: Mapping[str, int]
    location_counts: Mapping[str, int]
    location_reasons: Mapping[str, int]
    final_counts: Mapping[str, int]
    retained_by_family: Mapping[str, int]
    retained_by_location: Mapping[str, int]
    zero_retained_companies: tuple[str, ...]
    detail_fetch_count: int
    detail_failure_count: int
    companies: tuple[CompanyFilterRecord, ...]
    listings: tuple[FilterListingRecord, ...]

    @property
    def healthy(self) -> bool:
        return all(
            company.outcome in {AdapterOutcome.SUCCESS.value, AdapterOutcome.EMPTY.value}
            for company in self.companies
        )

    def as_json(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "scan_at": self.scan_at,
            "boundary": self.boundary,
            "registry_version": self.registry_version,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "profile_hash": self.profile_hash,
            "enabled_company_count": self.enabled_company_count,
            "outcome_counts": dict(self.outcome_counts),
            "listing_count": self.listing_count,
            "strict_recent_count": self.strict_recent_count,
            "uncertain_candidate_count": self.uncertain_candidate_count,
            "recency_excluded_count": self.recency_excluded_count,
            "role_counts": dict(self.role_counts),
            "role_rejection_reasons": dict(self.role_rejection_reasons),
            "location_counts": dict(self.location_counts),
            "location_reasons": dict(self.location_reasons),
            "final_counts": dict(self.final_counts),
            "retained_by_family": dict(self.retained_by_family),
            "retained_by_location": dict(self.retained_by_location),
            "zero_retained_companies": list(self.zero_retained_companies),
            "detail_fetch_count": self.detail_fetch_count,
            "detail_failure_count": self.detail_failure_count,
            "companies": [asdict(company) for company in self.companies],
            "listings": [_listing_as_json(listing) for listing in self.listings],
        }


@dataclass(frozen=True, slots=True)
class _PendingCompany:
    source: CompanySource
    company_name: str
    source_rank: int
    adapter_type: str
    result: AdapterResult
    attempt_count: int
    jobs: tuple[NormalizedJob, ...]


def verify_filters(
    registry: CompanySourceRegistry,
    adapters: AdapterRegistry,
    profile: SearchProfile,
    *,
    scan_at: datetime | None = None,
    generated_at: datetime | None = None,
    source_retry_count: int = 2,
    first_seen_lookup: Callable[[NormalizedJob], datetime | None] | None = None,
) -> FilterVerificationReport:
    """Collect and filter every enabled source without detail or LLM requests."""
    if scan_at is not None and scan_at.tzinfo is None:
        raise ValueError("scan_at must be timezone-aware")
    if generated_at is not None and generated_at.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    if source_retry_count < 0:
        raise ValueError("source_retry_count cannot be negative")

    pending: list[_PendingCompany] = []
    for entry in sorted(
        (item for item in registry.entries if item.source.enabled),
        key=lambda item: item.source_rank,
    ):
        source = entry.source
        result, attempts = list_jobs_with_retry(
            adapters.resolve(source), source, retry_count=source_retry_count
        )
        jobs = (
            tuple(normalize_job(job, location_policy=profile.location) for job in result.jobs)
            if result.outcome is AdapterOutcome.SUCCESS
            else ()
        )
        pending.append(
            _PendingCompany(
                source=source,
                company_name=source.company_name,
                source_rank=entry.source_rank,
                adapter_type=source.adapter_type.value,
                result=result,
                attempt_count=attempts,
                jobs=jobs,
            )
        )

    effective_scan_at = scan_at or datetime.now().astimezone()
    timestamp = generated_at or effective_scan_at
    listings: list[FilterListingRecord] = []
    companies: list[CompanyFilterRecord] = []
    for item in pending:
        company_listings: list[FilterListingRecord] = []
        recency_excluded_count = 0
        detail_fetch_count = 0
        detail_failure_count = 0
        for job in item.jobs:
            publication_verified = (
                item.source.date_strategy.verified_as_publication
                and job.date_basis is DateBasis.PUBLISHED
            )
            first_seen_at = first_seen_lookup(job) if first_seen_lookup is not None else None
            use_first_seen = first_seen_at is not None and not publication_verified
            assessment = assess_listing_recency(
                first_seen_at if use_first_seen else job.published_at,
                raw_date_text=None if use_first_seen else job.published_at_raw,
                basis=DateBasis.FIRST_SEEN if use_first_seen else job.date_basis,
                scan_at=effective_scan_at,
                window_days=profile.recency_window_days,
                uncertainty_mode=profile.date_uncertainty_mode,
                publication_date_verified=publication_verified,
            )
            if assessment.decision is RecencyDecision.INSIDE_WINDOW:
                section = CandidateSection.UNCERTAIN if use_first_seen else CandidateSection.STRICT
            elif assessment.decision is RecencyDecision.UNCERTAIN:
                section = CandidateSection.UNCERTAIN
            else:
                recency_excluded_count += 1
                continue
            role = filter_role(job.title_original, profile=profile)
            filtered_job = job
            location: LocationFilterResult | None = None
            if role.decision is not RoleDecision.REJECT:
                if _needs_workday_location_detail(job):
                    detail_fetch_count += 1
                    try:
                        filtered_job = _fetch_detail(job, item.source, adapters, profile)
                    except (HttpRequestError, ValueError):
                        detail_failure_count += 1
                        location = LocationFilterResult(
                            decision=LocationDecision.REVIEW,
                            reason_code="detail_location_unavailable",
                            reason="required public detail location could not be retrieved",
                        )
                if location is None:
                    location = filter_job_location(filtered_job, policy=profile.location)

                if (
                    location.decision is LocationDecision.PASS
                    and section is CandidateSection.UNCERTAIN
                    and job.source_type in {"jobvite", "successfactors"}
                ):
                    detail_fetch_count += 1
                    try:
                        filtered_job = _fetch_detail(job, item.source, adapters, profile)
                    except (HttpRequestError, ValueError):
                        detail_failure_count += 1
                    else:
                        detail_assessment = assess_listing_recency(
                            filtered_job.published_at,
                            raw_date_text=filtered_job.published_at_raw,
                            basis=filtered_job.date_basis,
                            scan_at=effective_scan_at,
                            window_days=profile.recency_window_days,
                            uncertainty_mode=profile.date_uncertainty_mode,
                            publication_date_verified=(
                                item.source.date_strategy.verified_as_publication
                                and filtered_job.date_basis is DateBasis.PUBLISHED
                            ),
                        )
                        if detail_assessment.decision is RecencyDecision.INSIDE_WINDOW:
                            section = CandidateSection.STRICT
                        elif detail_assessment.decision is not RecencyDecision.UNCERTAIN:
                            recency_excluded_count += 1
                            continue
            final = _final_decision(role, location)
            company_listings.append(
                FilterListingRecord(
                    company_id=job.company_id,
                    company_name=item.company_name,
                    source_rank=item.source_rank,
                    adapter_type=item.adapter_type,
                    title_original=filtered_job.title_original,
                    location_original=filtered_job.location_original,
                    canonical_url=filtered_job.canonical_url,
                    candidate_section=section,
                    date_basis=filtered_job.date_basis,
                    raw_date_text=filtered_job.published_at_raw,
                    role=role,
                    location=location,
                    final_decision=final,
                    normalized_job=filtered_job,
                )
            )
        listings.extend(company_listings)
        companies.append(
            _company_record(
                item,
                company_listings,
                recency_excluded_count,
                detail_fetch_count,
                detail_failure_count,
            )
        )

    role_counts = Counter(row.role.decision.value for row in listings)
    role_reasons = Counter(
        row.role.reason_code for row in listings if row.role.decision is RoleDecision.REJECT
    )
    location_rows = [row for row in listings if row.location is not None]
    location_counts = Counter(row.location.decision.value for row in location_rows if row.location)
    location_reasons = Counter(row.location.reason_code for row in location_rows if row.location)
    final_counts = Counter(row.final_decision.value for row in listings)
    retained = [row for row in listings if row.final_decision is FinalFilterDecision.RETAINED]
    return FilterVerificationReport(
        schema_version=1,
        generated_at=timestamp.isoformat(timespec="seconds"),
        scan_at=effective_scan_at.isoformat(timespec="seconds"),
        boundary=(effective_scan_at - timedelta(days=profile.recency_window_days)).isoformat(
            timespec="seconds"
        ),
        registry_version=registry.registry_version,
        profile_id=profile.profile_id,
        profile_version=profile.version,
        profile_hash=profile.content_hash,
        enabled_company_count=len(companies),
        outcome_counts=dict(sorted(Counter(item.result.outcome.value for item in pending).items())),
        listing_count=sum(len(item.jobs) for item in pending),
        strict_recent_count=sum(
            row.candidate_section is CandidateSection.STRICT for row in listings
        ),
        uncertain_candidate_count=sum(
            row.candidate_section is CandidateSection.UNCERTAIN for row in listings
        ),
        recency_excluded_count=sum(company.recency_excluded_count for company in companies),
        role_counts=dict(sorted(role_counts.items())),
        role_rejection_reasons=dict(sorted(role_reasons.items())),
        location_counts=dict(sorted(location_counts.items())),
        location_reasons=dict(sorted(location_reasons.items())),
        final_counts=dict(sorted(final_counts.items())),
        retained_by_family=dict(
            sorted(
                Counter(row.role.family_id or "conditional_description" for row in retained).items()
            )
        ),
        retained_by_location=dict(
            sorted(
                Counter(
                    location
                    for row in retained
                    if row.location is not None
                    for location in (row.location.matched_locations or (row.location.reason_code,))
                ).items()
            )
        ),
        zero_retained_companies=tuple(
            company.company_name for company in companies if company.retained_count == 0
        ),
        detail_fetch_count=sum(company.detail_fetch_count for company in companies),
        detail_failure_count=sum(company.detail_failure_count for company in companies),
        companies=tuple(companies),
        listings=tuple(listings),
    )


def write_filter_report(report: FilterVerificationReport, path: Path) -> None:
    """Write the complete sanitized machine-readable report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.as_json(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_filter_review(
    report: FilterVerificationReport,
    path: Path,
    *,
    sample_limit: int = 30,
) -> None:
    """Write the H6 human checkpoint artifact with stratified public-job samples."""
    retained = _stratified_sample(
        (row for row in report.listings if row.final_decision is FinalFilterDecision.RETAINED),
        key=lambda row: (
            _role_family_or_lane(row),
            row.location.reason_code if row.location is not None else "missing_location_result",
            row.adapter_type,
        ),
        limit=sample_limit,
    )
    rejected = _stratified_sample(
        (row for row in report.listings if row.final_decision is FinalFilterDecision.REJECTED),
        key=lambda row: (_decision_reason_code(row), row.adapter_type),
        limit=sample_limit,
    )
    reviews = _stratified_sample(
        (row for row in report.listings if row.final_decision is FinalFilterDecision.REVIEW),
        key=lambda row: (_decision_reason_code(row), row.adapter_type),
        limit=min(sample_limit, 20),
    )
    lines = [
        "# H6 role and location filter review",
        "",
        "## Checkpoint status",
        "",
        "**STOP — Human checkpoint H6: awaiting role and location sample review**",
        "",
        f"Generated from `{report.scan_at}` under profile `{report.profile_version}` "
        f"(`{report.profile_hash}`). The complete sanitized report is "
        "`reports/phase6_filter_verification.json`.",
        "",
        "## Reduction summary",
        "",
        f"- Enabled companies: {report.enabled_company_count}; source outcomes: "
        f"`{json.dumps(report.outcome_counts, sort_keys=True)}`.",
        f"- Listings observed: {report.listing_count:,}.",
        f"- Strict recent candidates: {report.strict_recent_count:,}; uncertain-date candidates: "
        f"{report.uncertain_candidate_count:,}; recency-excluded: "
        f"{report.recency_excluded_count:,}.",
        f"- Role outcomes: `{json.dumps(report.role_counts, sort_keys=True)}`.",
        f"- Location outcomes after role eligibility: "
        f"`{json.dumps(report.location_counts, sort_keys=True)}`.",
        f"- Final outcomes: `{json.dumps(report.final_counts, sort_keys=True)}`.",
        f"- Retained by role family/lane: "
        f"`{json.dumps(report.retained_by_family, sort_keys=True)}`.",
        f"- Retained by accepted-location category: "
        f"`{json.dumps(_retained_location_categories(report), sort_keys=True)}`.",
        f"- Pre-filter detail lookups: {report.detail_fetch_count}; failures: "
        f"{report.detail_failure_count}.",
        f"- Detail failures by company: "
        f"`{json.dumps(_detail_failures_by_company(report), sort_keys=True)}`. "
        "Failed Bank of America location lookups remain in the review section; failed SAP "
        "date lookups remain in the H5-approved uncertain-date lane.",
        f"- Companies with zero retained jobs: {len(report.zero_retained_companies)}.",
        f"- Zero-retained company classification: "
        f"`{json.dumps(_zero_retained_categories(report), sort_keys=True)}`.",
        "",
        "## Retained sample",
        "",
        *_sample_table(retained, prefix="K"),
        "",
        "## Rejected sample",
        "",
        *_sample_table(rejected, prefix="X"),
        "",
        "## Location-review sample",
        "",
        *_sample_table(reviews, prefix="L"),
        "",
        "## Companies with zero retained jobs",
        "",
        ", ".join(report.zero_retained_companies) or "None.",
        "",
        "## Review requested",
        "",
        "For every disputed row, reply with its row label and one of `should include`, "
        "`should exclude`, or `uncertain`, plus any missing target title or location vocabulary. "
        "Rows not disputed will be treated as approved after an explicit H6 approval.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _final_decision(
    role: RoleFilterResult, location: LocationFilterResult | None
) -> FinalFilterDecision:
    if role.decision is RoleDecision.REJECT:
        return FinalFilterDecision.REJECTED
    if location is None:
        raise AssertionError("eligible role requires a location result")
    if location.decision is LocationDecision.PASS:
        return FinalFilterDecision.RETAINED
    if location.decision is LocationDecision.REVIEW:
        return FinalFilterDecision.REVIEW
    return FinalFilterDecision.REJECTED


def _company_record(
    pending: _PendingCompany,
    listings: list[FilterListingRecord],
    recency_excluded_count: int,
    detail_fetch_count: int,
    detail_failure_count: int,
) -> CompanyFilterRecord:
    diagnostics = list(dict.fromkeys(item.category for item in pending.result.diagnostics))
    if pending.attempt_count > 1:
        diagnostics.insert(
            0,
            "source_retry_succeeded"
            if pending.result.outcome in {AdapterOutcome.SUCCESS, AdapterOutcome.EMPTY}
            else "source_retry_exhausted",
        )
    location_rows = [row for row in listings if row.location is not None]
    return CompanyFilterRecord(
        company_id=pending.source.company_id,
        company_name=pending.company_name,
        source_rank=pending.source_rank,
        adapter_type=pending.adapter_type,
        outcome=pending.result.outcome.value,
        complete=pending.result.complete,
        attempt_count=pending.attempt_count,
        page_count=pending.result.page_count,
        listing_count=len(pending.jobs),
        strict_recent_count=sum(
            row.candidate_section is CandidateSection.STRICT for row in listings
        ),
        uncertain_candidate_count=sum(
            row.candidate_section is CandidateSection.UNCERTAIN for row in listings
        ),
        recency_excluded_count=recency_excluded_count,
        explicit_role_count=sum(
            row.role.decision is RoleDecision.EXPLICIT_PASS for row in listings
        ),
        conditional_role_count=sum(
            row.role.decision is RoleDecision.CONDITIONAL_DESCRIPTION for row in listings
        ),
        role_rejected_count=sum(row.role.decision is RoleDecision.REJECT for row in listings),
        location_pass_count=sum(
            row.location is not None and row.location.decision is LocationDecision.PASS
            for row in location_rows
        ),
        location_review_count=sum(
            row.location is not None and row.location.decision is LocationDecision.REVIEW
            for row in location_rows
        ),
        location_rejected_count=sum(
            row.location is not None and row.location.decision is LocationDecision.REJECT
            for row in location_rows
        ),
        retained_count=sum(row.final_decision is FinalFilterDecision.RETAINED for row in listings),
        review_count=sum(row.final_decision is FinalFilterDecision.REVIEW for row in listings),
        rejected_count=sum(row.final_decision is FinalFilterDecision.REJECTED for row in listings),
        exception_categories=tuple(diagnostics),
        detail_fetch_count=detail_fetch_count,
        detail_failure_count=detail_failure_count,
    )


def _needs_workday_location_detail(job: NormalizedJob) -> bool:
    return job.source_type == "workday" and (
        job.source_metadata.get("listing_location_missing") is True
        or bool(re.fullmatch(r"\d+\s+locations?", job.location_original.strip(), re.IGNORECASE))
    )


def _fetch_detail(
    job: NormalizedJob,
    source: CompanySource,
    adapters: AdapterRegistry,
    profile: SearchProfile,
) -> NormalizedJob:
    adapter = adapters.resolve(source)
    if not isinstance(adapter, JobDetailAdapter):
        raise ValueError(f"adapter {source.adapter_type.value} does not support detail retrieval")
    return normalize_job(adapter.get_job_detail(source, job), location_policy=profile.location)


def _listing_as_json(row: FilterListingRecord) -> dict[str, object]:
    return {
        "company_id": row.company_id,
        "company_name": row.company_name,
        "source_rank": row.source_rank,
        "adapter_type": row.adapter_type,
        "title_original": row.title_original,
        "location_original": row.location_original,
        "canonical_url": row.canonical_url,
        "candidate_section": row.candidate_section.value,
        "date_basis": row.date_basis.value,
        "raw_date_text": row.raw_date_text,
        "role": asdict(row.role),
        "location": asdict(row.location) if row.location is not None else None,
        "final_decision": row.final_decision.value,
    }


def _stratified_sample(
    rows: Iterable[FilterListingRecord],
    *,
    key: Callable[[FilterListingRecord], object],
    limit: int,
) -> tuple[FilterListingRecord, ...]:
    buckets: dict[object, deque[FilterListingRecord]] = defaultdict(deque)
    for row in sorted(rows, key=lambda item: (item.source_rank, item.canonical_url)):
        buckets[key(row)].append(row)
    selected: list[FilterListingRecord] = []
    while buckets and len(selected) < limit:
        for bucket_key in list(buckets):
            selected.append(buckets[bucket_key].popleft())
            if not buckets[bucket_key]:
                del buckets[bucket_key]
            if len(selected) == limit:
                break
    return tuple(selected)


def _sample_table(rows: tuple[FilterListingRecord, ...], *, prefix: str) -> list[str]:
    lines = [
        "| Row | Company | Adapter | Role family/lane | Original title | Original location | "
        "Decision | Reason | Link |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for index, row in enumerate(rows, start=1):
        lines.append(
            "| "
            + " | ".join(
                (
                    f"{prefix}{index:02d}",
                    _markdown(row.company_name),
                    row.adapter_type,
                    _role_family_or_lane(row),
                    _markdown(row.title_original),
                    _markdown(row.location_original),
                    row.final_decision.value,
                    _markdown(_decision_reason(row)),
                    f"[job]({row.canonical_url})",
                )
            )
            + " |"
        )
    if not rows:
        lines.append("| — | — | — | — | — | — | — | No rows available. | — |")
    return lines


def _retained_location_categories(report: FilterVerificationReport) -> dict[str, int]:
    return dict(
        sorted(
            Counter(
                row.location.reason_code
                for row in report.listings
                if row.final_decision is FinalFilterDecision.RETAINED and row.location is not None
            ).items()
        )
    )


def _role_family_or_lane(row: FilterListingRecord) -> str:
    if row.role.family_id:
        return row.role.family_id
    if row.role.decision is RoleDecision.CONDITIONAL_DESCRIPTION:
        return "conditional_description"
    return "role_rejected"


def _detail_failures_by_company(report: FilterVerificationReport) -> dict[str, int]:
    return {
        company.company_name: company.detail_failure_count
        for company in report.companies
        if company.detail_failure_count
    }


def _zero_retained_categories(report: FilterVerificationReport) -> dict[str, int]:
    categories: Counter[str] = Counter()
    for company in report.companies:
        if company.retained_count:
            continue
        if company.strict_recent_count + company.uncertain_candidate_count == 0:
            categories["no_recency_candidates"] += 1
        elif company.location_review_count:
            categories["location_review_only"] += 1
        elif company.explicit_role_count + company.conditional_role_count:
            categories["eligible_roles_outside_india"] += 1
        else:
            categories["no_eligible_role_titles"] += 1
    return dict(sorted(categories.items()))


def _decision_reason(row: FilterListingRecord) -> str:
    if row.role.decision is RoleDecision.REJECT:
        return f"{row.role.reason_code}: {row.role.reason}"
    if row.location is None:
        return row.role.reason
    return f"{row.location.reason_code}: {row.location.reason}; role={row.role.reason_code}"


def _decision_reason_code(row: FilterListingRecord) -> str:
    if row.role.decision is RoleDecision.REJECT:
        return row.role.reason_code
    if row.location is not None:
        return row.location.reason_code
    return row.role.reason_code


def _markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()
