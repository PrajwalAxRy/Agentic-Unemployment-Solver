"""Replace same-date observations from their original baseline, never per invocation."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from datetime import date

from job_finder.collection import FilterVerificationReport
from job_finder.core.expiry_dryrun import ExpiryDryRun
from job_finder.core.job_probe import JobProbeResult
from job_finder.core.lifecycle import (
    CompanyRunContext,
    JobLifecycleState,
    JobStatus,
    record_absence,
    record_sighting,
)
from job_finder.core.reappearance import ReappearanceEvent, ReappearanceMonitor
from job_finder.persistence.batches import encode
from job_finder.persistence.repository import JobRecord, JobStateRepository
from job_finder.scan import LifecycleReport


def _baseline(connection: sqlite3.Connection, record: JobRecord, today: date) -> JobLifecycleState:
    current = JobLifecycleState(
        status=JobStatus(record.status),
        consecutive_absences=record.consecutive_absences,
        sighting_count=record.sighting_count,
        live_but_missing_days=record.live_but_missing_days,
        probe_state=record.probe_state,
        closed_at=record.closed_at,
        last_seen=record.last_seen_at.date(),
    )
    connection.execute(
        "INSERT OR IGNORE INTO daily_observations VALUES (?, ?, ?)",
        (record.job_key, today.isoformat(), encode(asdict(current))),
    )
    payload = json.loads(
        connection.execute(
            "SELECT baseline_json FROM daily_observations WHERE job_key = ? AND observed_date = ?",
            (record.job_key, today.isoformat()),
        ).fetchone()[0]
    )
    payload["status"] = JobStatus(payload["status"])
    for key in ("closed_at", "last_seen"):
        payload[key] = None if payload[key] is None else date.fromisoformat(payload[key])
    return JobLifecycleState(**payload)


def replace_daily_lifecycle(
    filtered: FilterVerificationReport,
    *,
    repository: JobStateRepository,
    connection: sqlite3.Connection,
    seen: set[str],
    today: date,
    probe: Callable[[str, bool], JobProbeResult | None] | None,
    dry_run: bool,
) -> LifecycleReport:
    """Called inside discovery's transaction, with all prefilter source identities."""
    dry = ExpiryDryRun()
    monitor = ReappearanceMonitor()
    sightings = absences = probes = closed = 0
    for company in filtered.companies:
        previous = connection.execute(
            "SELECT listing_count FROM daily_company_counts WHERE company_id = ? "
            "AND observed_date < ? ORDER BY observed_date DESC LIMIT 1",
            (company.company_id, today.isoformat()),
        ).fetchone()
        context = CompanyRunContext(
            scan_succeeded=company.outcome in {"success", "empty"},
            listing_complete=company.complete,
            current_listing_count=company.listing_count,
            previous_listing_count=None if previous is None else previous[0],
        )
        keys = connection.execute(
            "SELECT job_key FROM jobs WHERE company_id = ?", (company.company_id,)
        ).fetchall()
        for key in keys:
            record = repository.require(key[0])
            if (
                record.status == "closed"
                and record.job_key not in seen
                and record.closed_at != today
            ):
                continue
            state = _baseline(connection, record, today)
            if record.job_key in seen:
                if state.consecutive_absences or state.live_but_missing_days:
                    monitor.record(
                        ReappearanceEvent(
                            job_key=record.job_key,
                            company_id=record.company_id,
                            canonical_url=record.canonical_url,
                            absences_before_return=state.consecutive_absences,
                            was_probed_gone=state.probe_state
                            in {"http_gone", "closed_page_text", "redirected_to_search"},
                        )
                    )
                updated = record_sighting(state, today=today)
                sightings += 1
            elif state.status is JobStatus.CLOSED:
                continue
            else:
                result = (
                    probe(record.canonical_url, False)
                    if probe and context.trustworthy_for_expiry
                    else None
                )
                probes += result is not None
                absences += context.trustworthy_for_expiry
                if dry_run:
                    updated = dry.observe_absence(
                        job_key=record.job_key,
                        company_id=record.company_id,
                        canonical_url=record.canonical_url,
                        state=state,
                        context=context,
                        probe=result,
                        today=today,
                    )
                else:
                    updated = record_absence(state, context=context, probe=result, today=today)
                    closed += updated.status is JobStatus.CLOSED
            repository.record_lifecycle(record.job_key, updated)
        # A replacement that failed or collapsed invalidates today's earlier count.
        connection.execute(
            "DELETE FROM daily_company_counts WHERE company_id = ? AND observed_date = ?",
            (company.company_id, today.isoformat()),
        )
        if context.trustworthy_for_expiry:
            connection.execute(
                "INSERT INTO daily_company_counts VALUES (?, ?, ?)",
                (company.company_id, today.isoformat(), company.listing_count),
            )
    payload = dry.as_json()
    return LifecycleReport(
        dry_run=dry_run,
        sightings=sightings,
        absences=absences,
        probes_fired=probes,
        closed=closed,
        would_close=len(dry.would_close),
        checklist=payload["checklist"],  # type: ignore[arg-type]
        checklist_satisfied=bool(payload["checklist_satisfied"]),
        unmet_requirements=tuple(payload["unmet_requirements"]),  # type: ignore[arg-type]
        reappearance=monitor.as_json(),
    )
