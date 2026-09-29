"""Guarded Phase 8 live validation and H9 review reporting."""

from __future__ import annotations

import json
from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from job_finder.adapters.base import AdapterRegistry, JobDetailAdapter, list_jobs_with_retry
from job_finder.adapters.http_client import HttpRequestError
from job_finder.collection import (
    CandidateSection,
    FilterListingRecord,
    FilterVerificationReport,
    FinalFilterDecision,
)
from job_finder.core.company_registry import CompanySourceRegistry
from job_finder.core.job_contracts import NormalizedJob
from job_finder.core.search_profile import SearchProfile
from job_finder.core.source_contracts import AdapterOutcome, CompanySource
from job_finder.filters.locations import LocationDecision, LocationFilterResult
from job_finder.filters.roles import RoleDecision, RoleFilterResult
from job_finder.matching.evaluation_set import SeniorityEvaluationSet
from job_finder.matching.evaluator import (
    EvaluationOutcome,
    LLMProviderError,
    SeniorityEvaluator,
    UsageSnapshot,
)
from job_finder.matching.seniority import DetectedLevel, SeniorityDecision, SeniorityMatch
from job_finder.normalization.jobs import normalize_job


@dataclass(frozen=True, slots=True)
class ReviewedCaseResult:
    """Model result for one human-labelled evaluation example."""

    case_id: str
    title: str
    description: str
    expected_match: SeniorityMatch
    expected_level: DetectedLevel
    important_evidence: str
    human_rationale: str
    outcome: EvaluationOutcome | None
    provider_error: str | None = None

    @property
    def decision(self) -> SeniorityDecision | None:
        return self.outcome.decision if self.outcome is not None else None

    @property
    def decision_agrees(self) -> bool:
        return self.decision is not None and self.decision.seniority_match == self.expected_match

    @property
    def level_agrees(self) -> bool:
        return self.decision is not None and self.decision.detected_level is self.expected_level


@dataclass(frozen=True, slots=True)
class LiveCandidateResult:
    """One public job selected for limited unseen seniority validation."""

    case_id: str
    company_name: str
    adapter_type: str
    title: str
    location: str
    canonical_url: str
    candidate_section: CandidateSection
    role_family: str
    description: str
    outcome: EvaluationOutcome | None
    provider_error: str | None = None

    @property
    def decision(self) -> SeniorityDecision | None:
        return self.outcome.decision if self.outcome is not None else None


@dataclass(frozen=True, slots=True)
class CandidateCollectionIssue:
    """A public candidate that could not supply a usable description."""

    company_name: str
    title: str
    canonical_url: str
    category: str


@dataclass(frozen=True, slots=True)
class ReusedFilterEvidence:
    """Full-registry evidence reused while refreshing the exact live sample."""

    filter_scan_at: str
    enabled_company_count: int
    source_outcomes: Mapping[str, int]
    source_healthy: bool
    retained_candidate_count: int
    explicit_candidate_count: int
    conditional_candidate_count: int
    live_candidate_limit: int


@dataclass(frozen=True, slots=True)
class QualityMetrics:
    """Aggregate reviewed-set quality measurements used at H9."""

    total_count: int
    valid_count: int
    invalid_count: int
    decision_agreement_count: int
    decision_accuracy_percent: float
    level_agreement_count: int
    level_accuracy_percent: float
    false_acceptance_count: int
    false_rejection_count: int
    ambiguity_error_count: int
    recommended_threshold_passed: bool


@dataclass(frozen=True, slots=True)
class Phase8ValidationReport:
    """Complete H9 input without secrets or full provider responses."""

    schema_version: int
    generated_at: str
    registry_version: str
    profile_id: str
    profile_version: str
    profile_hash: str
    evaluation_set_version: str
    prompt_version: str
    model_policy: str
    filter_scan_at: str
    enabled_company_count: int
    source_outcomes: Mapping[str, int]
    source_healthy: bool
    retained_candidate_count: int
    explicit_candidate_count: int
    conditional_candidate_count: int
    live_candidate_limit: int
    collection_issues: tuple[CandidateCollectionIssue, ...]
    reviewed_cases: tuple[ReviewedCaseResult, ...]
    live_cases: tuple[LiveCandidateResult, ...]
    quality: QualityMetrics
    usage: UsageSnapshot

    def as_json(self) -> dict[str, object]:
        """Return a reviewable generated report with bounded description context."""
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "registry_version": self.registry_version,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "profile_hash": self.profile_hash,
            "evaluation_set_version": self.evaluation_set_version,
            "prompt_version": self.prompt_version,
            "model_policy": self.model_policy,
            "filter_scan_at": self.filter_scan_at,
            "enabled_company_count": self.enabled_company_count,
            "source_outcomes": dict(self.source_outcomes),
            "source_healthy": self.source_healthy,
            "retained_candidate_count": self.retained_candidate_count,
            "explicit_candidate_count": self.explicit_candidate_count,
            "conditional_candidate_count": self.conditional_candidate_count,
            "live_candidate_limit": self.live_candidate_limit,
            "collection_issues": [asdict(issue) for issue in self.collection_issues],
            "reviewed_cases": [_reviewed_case_as_json(item) for item in self.reviewed_cases],
            "live_cases": [_live_case_as_json(item) for item in self.live_cases],
            "quality": asdict(self.quality),
            "usage": asdict(self.usage),
        }


def run_reviewed_evaluation_set(
    evaluation_set: SeniorityEvaluationSet,
    evaluator: SeniorityEvaluator,
    *,
    target_description: str,
) -> tuple[ReviewedCaseResult, ...]:
    """Evaluate every reviewed example while retaining sanitized provider failures."""
    results: list[ReviewedCaseResult] = []
    for example in evaluation_set.examples:
        outcome: EvaluationOutcome | None = None
        provider_error: str | None = None
        try:
            outcome = evaluator.evaluate(
                title=example.title,
                description=example.description,
                target_description=target_description,
            )
        except LLMProviderError as error:
            provider_error = str(error)
        results.append(
            ReviewedCaseResult(
                case_id=example.example_id,
                title=example.title,
                description=example.description,
                expected_match=example.expected_match,
                expected_level=example.expected_level,
                important_evidence=example.important_evidence,
                human_rationale=example.human_rationale,
                outcome=outcome,
                provider_error=provider_error,
            )
        )
    return tuple(results)


def collect_live_candidates(
    filter_report: FilterVerificationReport,
    registry: CompanySourceRegistry,
    adapters: AdapterRegistry,
    profile: SearchProfile,
    *,
    limit: int,
) -> tuple[
    tuple[tuple[FilterListingRecord, NormalizedJob], ...],
    tuple[CandidateCollectionIssue, ...],
]:
    """Select a diverse explicit-role batch and retrieve only missing descriptions."""
    if limit <= 0:
        raise ValueError("live candidate limit must be positive")
    sources = {entry.source.company_id: entry.source for entry in registry.entries}
    eligible = (
        row
        for row in filter_report.listings
        if row.final_decision is FinalFilterDecision.RETAINED
        and row.role.decision is RoleDecision.EXPLICIT_PASS
    )
    ordered = _stratified_candidates(eligible)
    selected: list[tuple[FilterListingRecord, NormalizedJob]] = []
    issues: list[CandidateCollectionIssue] = []
    for row in ordered:
        job = row.normalized_job
        if job.description is None:
            source = sources[row.company_id]
            adapter = adapters.resolve(source)
            if not isinstance(adapter, JobDetailAdapter):
                issues.append(
                    CandidateCollectionIssue(
                        row.company_name,
                        row.title_original,
                        row.canonical_url,
                        "detail_adapter_unavailable",
                    )
                )
                continue
            try:
                job = normalize_job(
                    adapter.get_job_detail(source, job),
                    location_policy=profile.location,
                )
            except (HttpRequestError, ValueError):
                issues.append(
                    CandidateCollectionIssue(
                        row.company_name,
                        row.title_original,
                        row.canonical_url,
                        "detail_retrieval_failed",
                    )
                )
                continue
        if job.description is None or job.description_hash is None:
            issues.append(
                CandidateCollectionIssue(
                    row.company_name,
                    row.title_original,
                    row.canonical_url,
                    "description_missing",
                )
            )
            continue
        selected.append((row, job))
        if len(selected) == limit:
            break
    return tuple(selected), tuple(issues)


def recollect_live_candidates(
    prior_report_path: Path,
    registry: CompanySourceRegistry,
    adapters: AdapterRegistry,
    profile: SearchProfile,
    *,
    source_retry_count: int,
) -> tuple[
    ReusedFilterEvidence,
    tuple[tuple[FilterListingRecord, NormalizedJob], ...],
    tuple[CandidateCollectionIssue, ...],
]:
    """Refresh exact public jobs while reusing a completed full-registry gate."""
    if source_retry_count < 0:
        raise ValueError("source_retry_count cannot be negative")
    raw = json.loads(prior_report_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("reused Phase 8 report must use schema_version 1")
    live_raw = raw.get("live_cases")
    if not isinstance(live_raw, list) or not live_raw:
        raise ValueError("reused Phase 8 report must contain live_cases")

    sources = {entry.source.company_name: entry for entry in registry.entries}
    listed: dict[str, tuple[NormalizedJob, ...]] = {}
    selected: list[tuple[FilterListingRecord, NormalizedJob]] = []
    issues: list[CandidateCollectionIssue] = []
    for index, item_raw in enumerate(live_raw):
        item = _mapping(item_raw, f"live_cases[{index}]")
        path = f"live_cases[{index}]"
        company_name = _string(item, "company_name", path)
        title = _string(item, "title", path)
        canonical_url = _string(item, "canonical_url", path)
        entry = sources.get(company_name)
        if entry is None:
            raise ValueError(f"reused live company is not in registry: {company_name}")
        source = entry.source
        if company_name not in listed:
            result, _ = list_jobs_with_retry(
                adapters.resolve(source),
                source,
                retry_count=source_retry_count,
            )
            if result.outcome is not AdapterOutcome.SUCCESS:
                listed[company_name] = ()
                issues.append(
                    CandidateCollectionIssue(
                        company_name,
                        title,
                        canonical_url,
                        f"source_refresh_{result.outcome.value}",
                    )
                )
                continue
            listed[company_name] = tuple(
                normalize_job(job, location_policy=profile.location) for job in result.jobs
            )
        job = next(
            (
                candidate
                for candidate in listed[company_name]
                if candidate.canonical_url == canonical_url
            ),
            None,
        )
        if job is None:
            issues.append(
                CandidateCollectionIssue(company_name, title, canonical_url, "job_not_found")
            )
            continue
        detailed = _ensure_description(job, source, adapters, profile)
        if detailed is None:
            issues.append(
                CandidateCollectionIssue(
                    company_name,
                    title,
                    canonical_url,
                    "description_unavailable",
                )
            )
            continue
        candidate_section = CandidateSection(_string(item, "candidate_section", path))
        role_family = _string(item, "role_family", path)
        row = FilterListingRecord(
            company_id=source.company_id,
            company_name=company_name,
            source_rank=entry.source_rank,
            adapter_type=source.adapter_type.value,
            title_original=detailed.title_original,
            location_original=detailed.location_original,
            canonical_url=detailed.canonical_url,
            candidate_section=candidate_section,
            date_basis=detailed.date_basis,
            raw_date_text=detailed.published_at_raw,
            role=RoleFilterResult(
                RoleDecision.EXPLICIT_PASS,
                "reused_explicit_role",
                "explicit role eligibility preserved from full-registry H9 gate",
                role_family,
            ),
            location=LocationFilterResult(
                LocationDecision.PASS,
                "reused_india_location",
                "India eligibility preserved from full-registry H9 gate",
            ),
            final_decision=FinalFilterDecision.RETAINED,
            normalized_job=detailed,
        )
        selected.append((row, detailed))

    evidence = ReusedFilterEvidence(
        filter_scan_at=_required_json_string(raw, "filter_scan_at"),
        enabled_company_count=_required_json_int(raw, "enabled_company_count"),
        source_outcomes=_string_int_mapping(raw.get("source_outcomes"), "source_outcomes"),
        source_healthy=_required_json_bool(raw, "source_healthy"),
        retained_candidate_count=_required_json_int(raw, "retained_candidate_count"),
        explicit_candidate_count=_required_json_int(raw, "explicit_candidate_count"),
        conditional_candidate_count=_required_json_int(raw, "conditional_candidate_count"),
        live_candidate_limit=_required_json_int(raw, "live_candidate_limit"),
    )
    return evidence, tuple(selected), tuple(issues)


def run_live_candidate_batch(
    candidates: tuple[tuple[FilterListingRecord, NormalizedJob], ...],
    evaluator: SeniorityEvaluator,
    *,
    target_description: str,
) -> tuple[LiveCandidateResult, ...]:
    """Evaluate a bounded public-job batch that is separate from the labelled set."""
    results: list[LiveCandidateResult] = []
    for index, (row, job) in enumerate(candidates, start=1):
        if job.description is None:
            raise ValueError("live candidate requires a description")
        outcome: EvaluationOutcome | None = None
        provider_error: str | None = None
        try:
            outcome = evaluator.evaluate(
                title=job.title_original,
                description=job.description,
                target_description=target_description,
            )
        except LLMProviderError as error:
            provider_error = str(error)
        results.append(
            LiveCandidateResult(
                case_id=f"live-{index:02d}",
                company_name=row.company_name,
                adapter_type=row.adapter_type,
                title=job.title_original,
                location=job.location_original,
                canonical_url=job.canonical_url,
                candidate_section=row.candidate_section,
                role_family=row.role.family_id or "explicit_target_role",
                description=job.description,
                outcome=outcome,
                provider_error=provider_error,
            )
        )
    return tuple(results)


def quality_metrics(results: tuple[ReviewedCaseResult, ...]) -> QualityMetrics:
    """Measure exact reviewed-label agreement and unsafe opposite decisions."""
    valid = tuple(item for item in results if item.decision is not None)
    agreement = sum(item.decision_agrees for item in results)
    level_agreement = sum(item.level_agrees for item in results)
    false_acceptances = sum(
        item.expected_match is False
        and item.decision is not None
        and item.decision.seniority_match is True
        for item in results
    )
    false_rejections = sum(
        item.expected_match is True
        and item.decision is not None
        and item.decision.seniority_match is False
        for item in results
    )
    ambiguity_errors = sum(
        item.expected_match == "uncertain"
        and item.decision is not None
        and item.decision.seniority_match != "uncertain"
        for item in results
    )
    total = len(results)
    accuracy = round(100 * agreement / total, 2) if total else 0.0
    level_accuracy = round(100 * level_agreement / total, 2) if total else 0.0
    threshold_passed = (
        total > 0
        and len(valid) == total
        and accuracy >= 90.0
        and false_acceptances == 0
        and false_rejections == 0
        and ambiguity_errors == 0
    )
    return QualityMetrics(
        total_count=total,
        valid_count=len(valid),
        invalid_count=total - len(valid),
        decision_agreement_count=agreement,
        decision_accuracy_percent=accuracy,
        level_agreement_count=level_agreement,
        level_accuracy_percent=level_accuracy,
        false_acceptance_count=false_acceptances,
        false_rejection_count=false_rejections,
        ambiguity_error_count=ambiguity_errors,
        recommended_threshold_passed=threshold_passed,
    )


def write_phase8_validation_report(report: Phase8ValidationReport, path: Path) -> None:
    """Write the generated machine-readable H9 evidence outside version control."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.as_json(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_h9_review(report: Phase8ValidationReport, path: Path) -> None:
    """Write the H9 human review artifact with decisions and bounded evidence context."""
    disagreements = tuple(item for item in report.reviewed_cases if not item.decision_agrees)
    uncertain_or_invalid_reviewed = tuple(
        item
        for item in report.reviewed_cases
        if item.decision is None or item.decision.seniority_match == "uncertain"
    )
    uncertain_or_invalid_live = tuple(
        item
        for item in report.live_cases
        if item.decision is None or item.decision.seniority_match == "uncertain"
    )
    live_counts = Counter(_decision_text(item.decision) for item in report.live_cases)
    evidence_valid_count = sum(item.decision is not None for item in report.reviewed_cases) + sum(
        item.decision is not None for item in report.live_cases
    )
    threshold_status = "passed" if report.quality.recommended_threshold_passed else "did not pass"
    lines = [
        "# H9 seniority quality review",
        "",
        "## Checkpoint status",
        "",
        "**STOP — Human checkpoint H9: awaiting seniority threshold and uncertainty-policy "
        "approval.**",
        "",
        f"Generated `{report.generated_at}` with model policy `{report.model_policy}`, prompt "
        f"`{report.prompt_version}`, evaluation set `{report.evaluation_set_version}`, and search "
        f"profile `{report.profile_version}` (`{report.profile_hash}`).",
        "",
        "## Recommendation and result",
        "",
        "Recommended first-release threshold: at least 90% exact agreement on the reviewed "
        "`seniority_match` labels; 100% schema-valid results with locally verified verbatim "
        "evidence; zero false acceptances; zero false rejections; and every labelled ambiguous "
        "case preserved as `uncertain`.",
        "",
        f"**The reviewed set {threshold_status} the recommended threshold.**",
        "",
        "Recommended uncertainty policy: keep `uncertain` and invalid results in a dedicated "
        "manual-review section and never promote either to a match. Re-evaluate only after the "
        "description, profile, prompt, or model policy changes.",
        "",
        "## Aggregate quality",
        "",
        f"- Reviewed examples: {report.quality.total_count}; valid decisions: "
        f"{report.quality.valid_count}; invalid/manual-review outcomes: "
        f"{report.quality.invalid_count}.",
        f"- Exact decision agreement: {report.quality.decision_agreement_count}/"
        f"{report.quality.total_count} ({report.quality.decision_accuracy_percent:.2f}%).",
        f"- Detected-level agreement: {report.quality.level_agreement_count}/"
        f"{report.quality.total_count} ({report.quality.level_accuracy_percent:.2f}%). "
        "Level is diagnostic; eligibility is the release decision.",
        f"- False acceptances: {report.quality.false_acceptance_count}; false rejections: "
        f"{report.quality.false_rejection_count}; ambiguity errors: "
        f"{report.quality.ambiguity_error_count}.",
        f"- Limited live batch: {len(report.live_cases)} decisions; "
        f"outcomes `{json.dumps(dict(sorted(live_counts.items())), sort_keys=True)}`.",
        "",
        "## Full-registry deterministic gate used for sampling",
        "",
        f"- Enabled companies: {report.enabled_company_count}; source outcomes: "
        f"`{json.dumps(dict(report.source_outcomes), sort_keys=True)}`; healthy: "
        f"`{str(report.source_healthy).lower()}`.",
        f"- Retained role/location candidates: {report.retained_candidate_count}; explicit target "
        f"roles eligible for this seniority sample: {report.explicit_candidate_count}; "
        f"conditional-description candidates deliberately not sent: "
        f"{report.conditional_candidate_count}.",
        f"- Live candidate limit: {report.live_candidate_limit}; usable selected candidates: "
        f"{len(report.live_cases)}; description collection issues before reaching the limit: "
        f"{len(report.collection_issues)}.",
        "",
        "Generic conditional-description titles were excluded from this Phase 8 quality batch. "
        "Their separate deterministic substantive-AI-work check must pass before seniority "
        "evaluation in the Phase 9 scan orchestration.",
        "",
        "## Every reviewed-set disagreement",
        "",
        *_reviewed_table(disagreements),
        "",
        "## Every reviewed-set uncertain or invalid result",
        "",
        *_reviewed_table(uncertain_or_invalid_reviewed),
        "",
        "## Complete reviewed evaluation set",
        "",
        *_reviewed_table(report.reviewed_cases),
        "",
        "## Limited unseen live batch",
        "",
        *_live_table(report.live_cases),
        "",
        "## Every live uncertain or invalid result",
        "",
        *_live_table(uncertain_or_invalid_live),
        "",
        "## Evidence quality and usage",
        "",
        "- Completed decisions with locally verified verbatim description evidence: "
        f"{evidence_valid_count}.",
        f"- Requests: {report.usage.request_count}; estimated input tokens reserved: "
        f"{report.usage.estimated_input_tokens}; measured input tokens: "
        f"{report.usage.measured_input_tokens}; measured output tokens: "
        f"{report.usage.measured_output_tokens}.",
        "- No monetary estimate is claimed because the corporate gateway chargeback policy is "
        "not available.",
        "",
        "## Review requested",
        "",
        "Review the expected and actual decisions, evidence excerpts, and linked live job "
        "descriptions. Reply `approve H9 threshold and uncertainty policy`, or list corrections "
        "by case ID with the expected label (`true`, `false`, or `uncertain`).",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def retained_role_counts(report: FilterVerificationReport) -> tuple[int, int, int]:
    """Return retained, explicit, and conditional counts for H9 accounting."""
    retained = tuple(
        row for row in report.listings if row.final_decision is FinalFilterDecision.RETAINED
    )
    explicit = sum(row.role.decision is RoleDecision.EXPLICIT_PASS for row in retained)
    conditional = sum(row.role.decision is RoleDecision.CONDITIONAL_DESCRIPTION for row in retained)
    return len(retained), explicit, conditional


def _stratified_candidates(
    rows: Iterable[FilterListingRecord],
) -> tuple[FilterListingRecord, ...]:
    buckets: dict[tuple[str, CandidateSection], deque[FilterListingRecord]] = defaultdict(deque)
    for row in sorted(rows, key=lambda item: (item.source_rank, item.canonical_url)):
        buckets[(row.adapter_type, row.candidate_section)].append(row)
    selected: list[FilterListingRecord] = []
    while buckets:
        for key in sorted(buckets, key=lambda item: (item[1].value, item[0])):
            selected.append(buckets[key].popleft())
            if not buckets[key]:
                del buckets[key]
    return tuple(selected)


def _ensure_description(
    job: NormalizedJob,
    source: CompanySource,
    adapters: AdapterRegistry,
    profile: SearchProfile,
) -> NormalizedJob | None:
    if job.description is not None and job.description_hash is not None:
        return job
    adapter = adapters.resolve(source)
    if not isinstance(adapter, JobDetailAdapter):
        return None
    try:
        detailed = normalize_job(
            adapter.get_job_detail(source, job),
            location_policy=profile.location,
        )
    except (HttpRequestError, ValueError):
        return None
    if detailed.description is None or detailed.description_hash is None:
        return None
    return detailed


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _string(value: Mapping[str, object], key: str, path: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{path}.{key} must be a non-empty string")
    return item


def _required_json_string(value: Mapping[str, object], key: str) -> str:
    return _string(value, key, "report")


def _required_json_int(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise ValueError(f"report.{key} must be a non-negative integer")
    return item


def _required_json_bool(value: Mapping[str, object], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise ValueError(f"report.{key} must be a boolean")
    return item


def _string_int_mapping(value: object, path: str) -> Mapping[str, int]:
    raw = _mapping(value, path)
    result: dict[str, int] = {}
    for key, item in raw.items():
        if not isinstance(key, str) or not isinstance(item, int) or isinstance(item, bool):
            raise ValueError(f"{path} must map strings to integers")
        result[key] = item
    return result


def _reviewed_case_as_json(item: ReviewedCaseResult) -> dict[str, object]:
    decision = item.decision
    return {
        "case_id": item.case_id,
        "title": item.title,
        "description": item.description,
        "expected_match": item.expected_match,
        "expected_level": item.expected_level.value,
        "important_evidence": item.important_evidence,
        "human_rationale": item.human_rationale,
        "actual_decision": decision.as_json() if decision is not None else None,
        "decision_agrees": item.decision_agrees,
        "level_agrees": item.level_agrees,
        "disposition": (
            item.outcome.disposition.value if item.outcome is not None else "provider_error"
        ),
        "attempt_count": item.outcome.attempt_count if item.outcome is not None else 0,
        "validation_errors": list(item.outcome.errors) if item.outcome is not None else [],
        "provider_error": item.provider_error,
    }


def _live_case_as_json(item: LiveCandidateResult) -> dict[str, object]:
    decision = item.decision
    return {
        "case_id": item.case_id,
        "company_name": item.company_name,
        "adapter_type": item.adapter_type,
        "title": item.title,
        "location": item.location,
        "canonical_url": item.canonical_url,
        "candidate_section": item.candidate_section.value,
        "role_family": item.role_family,
        "description_context": _evidence_context(item.description, decision),
        "decision": decision.as_json() if decision is not None else None,
        "disposition": (
            item.outcome.disposition.value if item.outcome is not None else "provider_error"
        ),
        "attempt_count": item.outcome.attempt_count if item.outcome is not None else 0,
        "validation_errors": list(item.outcome.errors) if item.outcome is not None else [],
        "provider_error": item.provider_error,
    }


def _reviewed_table(items: tuple[ReviewedCaseResult, ...]) -> list[str]:
    lines = [
        "| Case | Title | Expected | Actual | Level expected/actual | Evidence | Status |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in items:
        decision = item.decision
        actual = _decision_text(decision)
        actual_level = decision.detected_level.value if decision is not None else "invalid"
        evidence = decision.evidence if decision is not None else item.provider_error or "invalid"
        status = "agree" if item.decision_agrees else "disagree"
        lines.append(
            f"| {_markdown(item.case_id)} | {_markdown(item.title)} | "
            f"{_match_text(item.expected_match)} | {actual} | "
            f"{item.expected_level.value} / {actual_level} | {_markdown(evidence)} | {status} |"
        )
    if not items:
        lines.append("| — | — | — | — | — | None. | — |")
    return lines


def _live_table(items: tuple[LiveCandidateResult, ...]) -> list[str]:
    lines = [
        "| Case | Company | Adapter | Title and location | Date lane | Decision | "
        "Evidence | Link |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in items:
        decision = item.decision
        evidence = decision.evidence if decision is not None else item.provider_error or "invalid"
        lines.append(
            f"| {_markdown(item.case_id)} | {_markdown(item.company_name)} | "
            f"{_markdown(item.adapter_type)} | {_markdown(item.title)} — "
            f"{_markdown(item.location)} | {item.candidate_section.value} | "
            f"{_decision_text(decision)} | {_markdown(evidence)} | "
            f"[job]({item.canonical_url}) |"
        )
    if not items:
        lines.append("| — | — | — | — | — | — | None. | — |")
    return lines


def _evidence_context(description: str, decision: SeniorityDecision | None) -> str:
    compact = " ".join(description.split())
    if decision is None:
        return compact[:1000]
    index = compact.casefold().find(" ".join(decision.evidence.split()).casefold())
    if index < 0:
        return compact[:1000]
    start = max(0, index - 300)
    end = min(len(compact), index + len(decision.evidence) + 500)
    return compact[start:end]


def _decision_text(decision: SeniorityDecision | None) -> str:
    return _match_text(decision.seniority_match) if decision is not None else "invalid"


def _match_text(value: SeniorityMatch) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return value


def _markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()
