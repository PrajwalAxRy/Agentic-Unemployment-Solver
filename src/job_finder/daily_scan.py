"""Daily scan admission, disposable discovery, and durable cumulative evaluation."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from job_finder.adapters.base import AdapterRegistry
from job_finder.adapters.connectivity import ConnectivityWaiter
from job_finder.checkpoint import CheckpointError
from job_finder.collection import (
    FilterListingRecord,
    FilterVerificationReport,
    FinalFilterDecision,
    collect_listings,
)
from job_finder.core.company_registry import CompanySourceRegistry
from job_finder.core.job_probe import JobProbeResult
from job_finder.core.search_profile import SearchProfile
from job_finder.cost import TokenRates
from job_finder.daily_lifecycle import replace_daily_lifecycle
from job_finder.filters.locations import LocationDecision
from job_finder.matching.evaluator import EvaluationDisposition, LLMProviderError, UsageSnapshot
from job_finder.matching.journal import JournalClient, fingerprint
from job_finder.matching.seniority import stored_merged_decision
from job_finder.matching.service import JobEvaluator
from job_finder.persistence.batches import (
    BatchRepository,
    encode,
    filter_metadata,
    india_date,
    listing_from_payload,
    listing_payload,
    restore_filter,
)
from job_finder.persistence.database import migrated_database
from job_finder.persistence.identity import job_identity
from job_finder.persistence.locking import ScanLock
from job_finder.persistence.repository import JobStateRepository
from job_finder.persistence.transactions import atomic
from job_finder.scan import (
    SCAN_REPORT_SCHEMA_VERSION,
    CompanyAccountingRecord,
    ScanOutcome,
    ScanReport,
    _company_accounting,
    _ensure_description,
    _filter_reviews,
    _first_seen,
    _metrics,
    _ProcessingCounts,
    _record_decision,
    _review,
    _scan_outcome,
    _source_failures,
)


@dataclass(frozen=True)
class DailyScanResult:
    report: ScanReport
    admission_date: str
    pending_count: int
    halt_reason: str | None

    @property
    def exit_code(self) -> int:
        if self.halt_reason == "discovery_only":
            return self.report.outcome.exit_code
        return 6 if self.pending_count else self.report.outcome.exit_code


def discovery_fingerprint(registry: CompanySourceRegistry, profile: SearchProfile) -> str:
    settings = asdict(profile)
    for key in ("seniority", "version", "content_hash"):
        settings.pop(key)
    return fingerprint({"registry": asdict(registry), "filters": settings})


def evaluation_fingerprint(evaluator: JobEvaluator, profile: SearchProfile) -> str:
    return fingerprint(
        {
            "evaluator": getattr(
                evaluator,
                "configuration_fingerprint",
                {"prompt": evaluator.prompt_version, "model": evaluator.model_policy},
            ),
            "seniority": asdict(profile.seniority),
        }
    )


def _location(row: FilterListingRecord) -> str | None:
    return (
        row.location_original
        if row.location and row.location.decision is LocationDecision.REVIEW
        else None
    )


# Sent in place of a missing description so the model judges the title alone (the merged
# prompt has a rule for exactly this). It is part of the rendered request, so a description
# that appears later changes the fingerprint and the job is judged again rather than keeping
# a title-only verdict. Observed 2026-10-02: 79 of 3,806 candidates had no description (69
# from one board whose postings have an empty JD); all went to review, all were non-AI titles.
NO_DESCRIPTION = "The source published no job description for this posting."

# Filter outcomes that enter LLM evaluation. REVIEW means the role passed but location is
# unresolved; the merged call then also answers the location question.
_ADMITTED = frozenset({FinalFilterDecision.RETAINED, FinalFilterDecision.REVIEW})


def _description(row: FilterListingRecord) -> str:
    return row.normalized_job.description or NO_DESCRIPTION


def candidate_fingerprint(
    evaluator: JobEvaluator, row: FilterListingRecord, profile: SearchProfile
) -> str:
    request = evaluator.build_request(
        title=row.title_original,
        description=_description(row),
        target_description=profile.seniority.description,
        location_original=_location(row),
    )
    return fingerprint({"request": asdict(request), "policy": evaluator.model_policy})


def run_daily_scan(
    registry: CompanySourceRegistry,
    adapters: AdapterRegistry,
    profile: SearchProfile,
    evaluator: JobEvaluator,
    *,
    database_path: Path,
    lock_path: Path,
    command: str = "scan",
    discovery_only: bool = False,
    source_retry_count: int = 2,
    expiry_dry_run: bool = True,
    job_probe: Callable[[str, bool], JobProbeResult | None] | None = None,
    connectivity: ConnectivityWaiter | None = None,
    on_item_start: Callable[[str], None] | None = None,
    progress: Callable[[str], None] | None = None,
    rates: TokenRates | None = None,
    on_admitted: Callable[[str, bool], None] | None = None,
    on_result: Callable[[DailyScanResult], None] | None = None,
    on_finally: Callable[[sqlite3.Connection], None] | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    scan_at: datetime | None = None,
) -> DailyScanResult:
    """Callbacks for logs/reports/accounting execute while the shared lock is held."""
    if command not in {"scan", "evaluate", "force_reevaluate"}:
        raise ValueError("unsupported scan command")
    if discovery_only and command != "scan":
        raise ValueError("--discovery-only is only available with a fresh scan")
    with ScanLock(lock_path), migrated_database(database_path) as connection:
        start = clock()
        batches = BatchRepository(connection)
        jobs = JobStateRepository(connection)
        config = evaluation_fingerprint(evaluator, profile)
        discovery = discovery_fingerprint(registry, profile)
        if command != "scan":
            current = batches.require_fresh(start)
            try:
                metadata = json.loads(current["metadata_json"])
                restore_filter(metadata["filtered"], batches.candidates())
                datetime.fromisoformat(metadata["started_at"])
                for item in metadata["accounting"]:
                    CompanyAccountingRecord(**item)
            except (ValueError, KeyError, TypeError, CheckpointError) as error:
                raise CheckpointError(
                    "saved database batch is corrupt; run a fresh scan"
                ) from error
            if current["discovery_config"] != discovery:
                raise CheckpointError(
                    "source or discovery filter configuration changed; run a fresh scan"
                )
            if command == "evaluate" and current["evaluation_config"] != config:
                raise CheckpointError(
                    "evaluation rules changed; use force_reevaluate or run a fresh scan"
                )
            day = current["admission_date"]
        else:
            day = india_date(start)
        try:
            if command == "scan":
                batches.discard("new_scan")
            elif command == "force_reevaluate":
                batches.restart(config)
            if on_admitted:
                on_admitted(day, command != "evaluate")
            if command == "scan":
                seen: set[str] = set()
                if progress:
                    enabled = sum(entry.source.enabled for entry in registry.entries)
                    progress(f"phase=source_collection status=started companies={enabled}")
                filtered = collect_listings(
                    registry,
                    adapters,
                    profile,
                    source_retry_count=source_retry_count,
                    first_seen_lookup=lambda job: _first_seen(jobs, job),
                    progress=progress,
                    waiter=connectivity,
                    on_item_start=on_item_start,
                    scan_at=scan_at,
                    on_listing=lambda job: seen.add(job_identity(job).job_key),
                )
                if _scan_outcome(filtered) is ScanOutcome.FAILED:
                    raise RuntimeError("no enabled source completed; discovery discarded")
                _publish(
                    filtered,
                    registry,
                    adapters,
                    profile,
                    jobs,
                    batches,
                    start=start,
                    day=day,
                    config=config,
                    discovery=discovery,
                    seen=seen,
                    dry_run=expiry_dry_run,
                    probe=job_probe,
                    progress=progress,
                )
            halt_reason = (
                "discovery_only"
                if discovery_only
                else _evaluate(batches, jobs, evaluator, profile, rates, progress, clock)
            )
            report = _report(batches, jobs, profile, evaluator, start, clock(), halt_reason)
            pending = sum(row["result_json"] is None for row in batches.candidates())
            result = DailyScanResult(report, day, pending, halt_reason)
            if progress:
                status = "deferred" if discovery_only else "halted" if pending else "complete"
                progress(
                    f"phase=candidate_evaluation status={status} "
                    f"pending={pending} reason={halt_reason or 'none'}"
                )
            if on_result:
                on_result(result)
            return result
        except BaseException as error:
            logging.getLogger(__name__).warning("run=stopped exception=%s", type(error).__name__)
            raise
        finally:
            if on_finally:
                on_finally(connection)


def _publish(
    filtered: FilterVerificationReport,
    registry: CompanySourceRegistry,
    adapters: AdapterRegistry,
    profile: SearchProfile,
    jobs: JobStateRepository,
    batches: BatchRepository,
    *,
    start: datetime,
    day: str,
    config: str,
    discovery: str,
    seen: set[str],
    dry_run: bool,
    probe: Callable[[str, bool], JobProbeResult | None] | None,
    progress: Callable[[str], None] | None,
) -> None:
    sources = {entry.source.company_id: entry.source for entry in registry.entries}
    prepared = []
    identities: set[str] = set()
    for row in filtered.listings:
        # Location-review rows are evaluated too (to_change.md 2.4, decided): the merged
        # call answers the location question the deterministic filter could not. They were
        # previously reported straight to review, so the location judgment never ran and
        # every unresolved row reached the user without a relevance check.
        if row.final_decision not in _ADMITTED:
            continue
        key = job_identity(row.normalized_job).job_key
        if key in identities:
            continue
        identities.add(key)
        detailed, fetched, error = _ensure_description(
            row.normalized_job, sources[row.company_id], adapters, profile
        )
        prepared.append(
            (replace(row, normalized_job=detailed or row.normalized_job), key, fetched, error)
        )
        if progress:
            progress(
                f"phase=description_collection progress={len(prepared)} company={row.company_id}"
            )
    # Only rows that did not enter evaluation remain deterministic reviews.
    leftover = tuple(
        row
        for row in filtered.listings
        if row.final_decision is FinalFilterDecision.REVIEW
        and job_identity(row.normalized_job).job_key not in identities
    )
    metadata = {
        "filtered": filter_metadata(replace(filtered, listings=leftover)),
        "accounting": [asdict(row) for row in _company_accounting(registry)],
        "started_at": start.isoformat(),
        "profile_id": profile.profile_id,
        "profile_version": profile.version,
        "profile_hash": profile.content_hash,
    }
    connection = batches.connection
    observed = datetime.fromisoformat(filtered.scan_at).astimezone(UTC)
    with atomic(connection):
        connection.execute(
            "INSERT INTO daily_batch VALUES (1, ?, ?, ?, ?, ?, 0, ?, NULL)",
            (uuid4().hex, day, uuid4().hex, config, discovery, encode(metadata)),
        )
        for index, (row, key, fetched, error) in enumerate(prepared):
            observation = jobs.observe_listing(
                row.normalized_job, observed_at=observed, profile_version=profile.version
            )
            connection.execute(
                "INSERT INTO batch_candidates(ordinal, job_key, payload_json, is_new, "
                "fetch_count, description_error) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (index, key, encode(listing_payload(row)), observation.is_new, fetched, error),
            )
        # Presence came from every source listing, including recency/location/title exclusions.
        # Update only already-known non-candidates; rejected new listings are not persisted.
        for key in seen - identities:
            connection.execute(
                "UPDATE jobs SET last_seen_at = ?, updated_at = ? WHERE job_key = ?",
                (observed.isoformat(), observed.isoformat(), key),
            )
        lifecycle = replace_daily_lifecycle(
            filtered,
            repository=jobs,
            connection=connection,
            seen=seen,
            today=date.fromisoformat(india_date(observed)),
            probe=probe,
            dry_run=dry_run,
        )
        observation_day = india_date(observed)
        # Only today's baseline is needed for replacement. Durable counters live in jobs.
        connection.execute(
            "DELETE FROM daily_observations WHERE observed_date < ?", (observation_day,)
        )
        connection.execute(
            "DELETE FROM daily_company_counts WHERE observed_date < "
            "(SELECT MAX(previous.observed_date) FROM daily_company_counts AS previous "
            "WHERE previous.company_id = daily_company_counts.company_id "
            "AND previous.observed_date < ?)",
            (observation_day,),
        )
        connection.execute(
            "UPDATE daily_batch SET lifecycle_json = ?", (encode(asdict(lifecycle)),)
        )
    if progress:
        progress(
            f"phase=discovery_checkpoint status=saved candidates={len(prepared)} "
            "expires=midnight_IST"
        )


def _evaluate(
    batches: BatchRepository,
    jobs: JobStateRepository,
    evaluator: JobEvaluator,
    profile: SearchProfile,
    rates: TokenRates | None,
    progress: Callable[[str], None] | None,
    clock: Callable[[], datetime],
) -> str | None:
    current = batches.current()
    assert current is not None
    original = evaluator.client
    journal = JournalClient(
        original,
        batches.connection,
        attempt_id=current["attempt_id"],
        batch_date=current["admission_date"],
        rates=rates,
        clock=clock,
    )
    evaluator.client = journal
    candidates = batches.candidates()
    try:
        for candidate in candidates:
            if candidate["result_json"] is not None:
                continue
            ordinal = candidate["ordinal"]
            row = listing_from_payload(json.loads(candidate["payload_json"]))
            if progress:
                progress(
                    f"phase=candidate_evaluation progress={ordinal + 1}/{len(candidates)} "
                    f"company={row.company_id}"
                )
            # A missing description no longer skips evaluation: the title is judged alone,
            # and the reason is kept on the result so reports still count it.
            description_error = candidate["description_error"] or (
                None if row.normalized_job.description else "missing_description"
            )
            key = candidate_fingerprint(evaluator, row, profile)
            cached = None if current["force"] else batches.cache(key)
            result: dict[str, Any]
            if cached is not None:
                result = {**cached, "cached": True}
            else:
                journal.begin_candidate(ordinal)
                try:
                    outcome = evaluator.evaluate(
                        title=row.title_original,
                        description=_description(row),
                        target_description=profile.seniority.description,
                        location_original=_location(row),
                    )
                except LLMProviderError:
                    return "llm_provider_failure"
                if outcome.disposition is EvaluationDisposition.BUDGET_EXHAUSTED:
                    return "budget_exhausted"
                result = {
                    "disposition": outcome.disposition.value,
                    "cached": False,
                    "decision": None if outcome.decision is None else outcome.decision.as_json(),
                    "judgment": None if outcome.judgment is None else asdict(outcome.judgment),
                    "errors": list(outcome.errors),
                }
            if description_error:
                result = {**result, "description_error": description_error}
            _commit_result(batches, candidate, row, result, key, profile, evaluator, clock())
    finally:
        evaluator.client = original
    return None


def _commit_result(
    batches: BatchRepository,
    candidate: sqlite3.Row,
    row: FilterListingRecord,
    result: dict[str, Any],
    key: str,
    profile: SearchProfile,
    evaluator: JobEvaluator,
    completed: datetime,
) -> None:
    judgment = result.get("judgment") or {}
    decision = result.get("decision")
    with atomic(batches.connection):
        batches.connection.execute(
            "UPDATE jobs SET description = ?, description_hash = ?, profile_version = ?, "
            "prompt_version = ?, "
            "model_policy = ?, evaluation_status = ?, seniority_result_json = ?, verdict = ?, "
            "verdict_at = CASE WHEN ? IS NULL THEN verdict_at ELSE COALESCE(verdict_at, ?) END, "
            "required_experience = ?, relevance_evidence = ?, relevance_reason = ?, "
            "location_evidence = ?, location_reason = ?, updated_at = ? WHERE job_key = ?",
            (
                row.normalized_job.description,
                row.normalized_job.description_hash,
                profile.version,
                evaluator.prompt_version,
                evaluator.model_policy,
                "completed" if decision else "failed",
                encode(
                    decision
                    or {
                        "reason_code": "invalid_seniority_output",
                        "errors": result.get("errors", []),
                    }
                ),
                judgment.get("relevance"),
                judgment.get("relevance"),
                completed.isoformat(),
                None if decision is None else decision["required_experience"],
                judgment.get("relevance_evidence"),
                judgment.get("relevance_reason"),
                judgment.get("location_evidence"),
                judgment.get("location_reason"),
                completed.isoformat(),
                candidate["job_key"],
            ),
        )
        batches.finish_candidate(candidate["ordinal"], result, key)


def _report(
    batches: BatchRepository,
    jobs: JobStateRepository,
    profile: SearchProfile,
    evaluator: JobEvaluator,
    start: datetime,
    finish: datetime,
    halt_reason: str | None,
) -> ScanReport:
    current = batches.current()
    assert current is not None
    metadata = json.loads(current["metadata_json"])
    candidates = batches.candidates()
    filtered = restore_filter(metadata["filtered"], candidates)
    accounting = tuple(CompanyAccountingRecord(**item) for item in metadata["accounting"])
    counts = _ProcessingCounts()
    matches: list[Any] = []
    uncertain: list[Any] = []
    # Location-review rows that entered evaluation are reported from their judgment below,
    # not again as deterministic reviews.
    admitted = {candidate["job_key"] for candidate in candidates}
    reviews = _filter_reviews(
        replace(
            filtered,
            listings=tuple(
                row
                for row in filtered.listings
                if job_identity(row.normalized_job).job_key not in admitted
            ),
        )
    )
    counts.review = len(reviews)
    for candidate in candidates:
        counts.observed += 1
        counts.new += candidate["is_new"]
        counts.duplicate += not candidate["is_new"]
        counts.detail_fetch += candidate["fetch_count"]
        if candidate["result_json"] is None:
            counts.budget_halted += 1
            continue
        row = listing_from_payload(json.loads(candidate["payload_json"]))
        result = json.loads(candidate["result_json"])
        # Title-only verdicts still count as description failures. The old
        # "description_unavailable" disposition remains for batches saved before them.
        counts.detail_failure += bool(result.get("description_error")) or (
            result["disposition"] == "description_unavailable"
        )
        if result["disposition"] in {"manual_review", "description_unavailable"}:
            counts.review += 1
            reviews.append(_review(row, result["disposition"], "; ".join(result["errors"])))
            continue
        counts.cache_hit += bool(result["cached"])
        counts.evaluated += not result["cached"]
        counts.conditional_pass += 1
        judgment = result.get("judgment") or {}
        if judgment.get("relevance") == "unrelated":
            counts.conditional_reject += 1
            continue
        counts.relevance_peripheral += judgment.get("relevance") == "peripheral"
        if judgment.get("location_eligible") is False:
            counts.location_rejected += 1
            continue
        if judgment.get("location_eligible") == "uncertain":
            counts.review += 1
            reviews.append(
                _review(
                    row,
                    "location_uncertain",
                    judgment.get("location_reason") or "Location eligibility is uncertain",
                    evidence=judgment.get("location_evidence"),
                )
            )
            continue
        before = len(matches), len(uncertain)
        _record_decision(
            row,
            stored_merged_decision(result["decision"]),
            jobs.require(candidate["job_key"]),
            reportable=True,
            matches=matches,
            uncertain_dates=uncertain,
            reviews=reviews,
            counts=counts,
        )
        if len(matches) > before[0]:
            matches[-1] = replace(matches[-1], new_identity=bool(candidate["is_new"]))
        if len(uncertain) > before[1]:
            uncertain[-1] = replace(uncertain[-1], new_identity=bool(candidate["is_new"]))
    usage = batches.connection.execute(
        "SELECT COUNT(*), COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0), "
        "COALESCE(SUM(input_tokens IS NULL OR output_tokens IS NULL), 0) "
        "FROM llm_requests WHERE attempt_id = ?",
        (current["attempt_id"],),
    ).fetchone()
    failures = _source_failures(filtered)
    original_start = datetime.fromisoformat(metadata["started_at"])
    metrics = _metrics(filtered, accounting, failures, counts)
    if halt_reason == "discovery_only":
        metrics = replace(metrics, llm_budget_halted_count=0)
    return ScanReport(
        schema_version=SCAN_REPORT_SCHEMA_VERSION,
        run_id=current["attempt_id"],
        started_at=original_start.isoformat(),
        completed_at=finish.isoformat(),
        duration_seconds=max(0.0, (finish - original_start).total_seconds()),
        outcome=_scan_outcome(filtered),
        registry_version=filtered.registry_version,
        profile_id=metadata["profile_id"],
        profile_version=profile.version,
        profile_hash=profile.content_hash,
        prompt_version=evaluator.prompt_version,
        model_policy=evaluator.model_policy,
        source_outcomes=filtered.outcome_counts,
        company_status_counts=dict(Counter(item.status for item in accounting)),
        metrics=metrics,
        usage=UsageSnapshot(usage[0], 0, usage[1], usage[2]),
        matching_jobs=tuple(matches),
        date_uncertain_jobs=tuple(uncertain),
        review_candidates=tuple(reviews),
        source_failures=failures,
        company_accounting=accounting,
        lifecycle=json.loads(current["lifecycle_json"]) if current["lifecycle_json"] else None,
        timing=filtered.timing,
        batch_date=current["admission_date"],
        evaluation_complete=not counts.budget_halted,
        pending_count=counts.budget_halted,
        halt_reason=halt_reason,
        unknown_usage_request_count=usage[3],
    )
