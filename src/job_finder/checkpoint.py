"""Resume state for a scan that stopped before evaluating every retained job.

A scan spends roughly three and a half hours scraping 150 companies and running the
deterministic filter before the first LLM call is made. When the run budget runs out
partway through evaluation -- which is what happened on 2026-09-30, at job 140 of 3,677 --
re-running from the top pays that three and a half hours again to rebuild a list the
previous run already had.

This module writes the still-unevaluated rows to disk so ``scan --resume`` can go straight
to the LLM stage.

The checkpoint is a *cache of work in progress*, never a source of truth. Everything in it
is re-derived from the live site on the next full scan, and the job store remains
authoritative for what has actually been evaluated. Two consequences follow, and both are
deliberate:

* A stale checkpoint is refused rather than trusted (see ``STALENESS_LIMIT``). Postings
  close, and evaluating a job that disappeared two days ago wastes budget on a row the
  next scan would retire anyway.
* A checkpoint that cannot be parsed is an error, not a warning. Silently falling back to
  a full scan would turn "resume" into "spend four hours" without the operator noticing.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.core.validation import optional_string, required_string
from job_finder.filters.locations import LocationDecision, LocationFilterResult
from job_finder.filters.roles import RoleDecision, RoleFilterResult

SCHEMA_VERSION = 1
DEFAULT_CHECKPOINT_PATH = Path("state/resume_checkpoint.json")

STALENESS_LIMIT = timedelta(hours=24)
"""How old a checkpoint may be before ``--resume`` refuses it.

Job postings close. Resuming onto a two-day-old snapshot spends real budget on rows the
next scan would retire as absent, and worse, reports them to the user as live openings.
Twenty-four hours is the point at which re-scraping is cheaper than acting on stale data.
"""


class CheckpointError(RuntimeError):
    """A checkpoint could not be read, or is not safe to resume from."""


@dataclass(frozen=True, slots=True)
class CheckpointRow:
    """One retained listing that had not been evaluated when the run stopped.

    This is a deliberately reduced form of ``FilterListingRecord``. Only the fields the
    evaluation stage actually reads are stored: enough to re-run the LLM stage, not enough
    to reconstruct a filter report. Keeping it minimal means a schema change to the filter
    report does not silently invalidate checkpoints.
    """

    company_id: str
    title_original: str
    location_original: str
    canonical_url: str
    candidate_section: str
    """strict_recent vs uncertain_date -- the report tiers rows on this, so guessing it
    on resume would silently move jobs between sections."""
    role: RoleFilterResult
    location: LocationFilterResult | None
    normalized_job: NormalizedJob


@dataclass(frozen=True, slots=True)
class ResumeCheckpoint:
    """Everything ``scan --resume`` needs to restart the evaluation stage."""

    schema_version: int
    created_at: datetime
    run_id: str
    scan_at: str
    profile_version: str
    prompt_version: str
    model_policy: str
    evaluated_before_halt: int
    reason: str
    rows: tuple[CheckpointRow, ...]

    @property
    def age(self) -> timedelta:
        return datetime.now(UTC) - self.created_at

    @property
    def is_stale(self) -> bool:
        return self.age > STALENESS_LIMIT


def write_checkpoint(checkpoint: ResumeCheckpoint, path: Path) -> None:
    """Persist a checkpoint, replacing any previous one atomically.

    Written to a temporary sibling and renamed, because the alternative -- truncating the
    real file and failing partway -- destroys the only record of what remained. A halted
    run has already lost time; it should not also lose its resume point.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": checkpoint.schema_version,
        "created_at": checkpoint.created_at.isoformat(),
        "run_id": checkpoint.run_id,
        "scan_at": checkpoint.scan_at,
        "profile_version": checkpoint.profile_version,
        "prompt_version": checkpoint.prompt_version,
        "model_policy": checkpoint.model_policy,
        "evaluated_before_halt": checkpoint.evaluated_before_halt,
        "reason": checkpoint.reason,
        "rows": [_row_as_json(row) for row in checkpoint.rows],
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", "utf-8")
    temporary.replace(path)


def read_checkpoint(path: Path) -> ResumeCheckpoint:
    """Load a checkpoint, raising ``CheckpointError`` if it is unusable."""
    if not path.exists():
        raise CheckpointError(f"no checkpoint at {path}; run a full scan first")
    try:
        raw = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CheckpointError(f"checkpoint at {path} could not be read: {error}") from error
    if not isinstance(raw, dict):
        raise CheckpointError(f"checkpoint at {path} is not a JSON object")

    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        raise CheckpointError(
            f"checkpoint schema_version {version!r} is not supported "
            f"(expected {SCHEMA_VERSION}); run a full scan"
        )
    rows_raw = raw.get("rows")
    if not isinstance(rows_raw, list):
        raise CheckpointError("checkpoint 'rows' must be a list")
    try:
        created_at = datetime.fromisoformat(required_string(raw, "created_at"))
    except ValueError as error:
        raise CheckpointError(f"checkpoint created_at is not a timestamp: {error}") from error
    if created_at.tzinfo is None:
        raise CheckpointError("checkpoint created_at must be timezone-aware")

    return ResumeCheckpoint(
        schema_version=SCHEMA_VERSION,
        created_at=created_at,
        run_id=required_string(raw, "run_id"),
        scan_at=required_string(raw, "scan_at"),
        profile_version=required_string(raw, "profile_version"),
        prompt_version=required_string(raw, "prompt_version"),
        model_policy=required_string(raw, "model_policy"),
        evaluated_before_halt=int(raw.get("evaluated_before_halt") or 0),
        reason=str(raw.get("reason") or "unknown"),
        rows=tuple(_row_from_json(entry, index) for index, entry in enumerate(rows_raw)),
    )


def assert_resumable(
    checkpoint: ResumeCheckpoint,
    *,
    profile_version: str,
    prompt_version: str,
    model_policy: str,
) -> None:
    """Refuse a checkpoint that is stale or was built under different judgement rules.

    The version checks mirror the evaluation cache's reuse condition. If the profile,
    prompt or model has changed since the halt, the cached verdicts those rows would join
    are themselves invalid -- resuming would produce one report containing two
    incompatible sets of judgements, which is worse than re-scanning.
    """
    if checkpoint.is_stale:
        hours = checkpoint.age.total_seconds() / 3600
        limit_hours = STALENESS_LIMIT.total_seconds() / 3600
        raise CheckpointError(
            f"checkpoint is {hours:.1f}h old (limit {limit_hours:.0f}h); "
            "postings may have closed -- run a full scan instead"
        )
    mismatches = [
        f"{name}: checkpoint={was!r} now={now!r}"
        for name, was, now in (
            ("profile_version", checkpoint.profile_version, profile_version),
            ("prompt_version", checkpoint.prompt_version, prompt_version),
            ("model_policy", checkpoint.model_policy, model_policy),
        )
        if was != now
    ]
    if mismatches:
        raise CheckpointError(
            "configuration changed since the checkpoint was written, so cached verdicts "
            "no longer agree with it (" + "; ".join(mismatches) + "); run a full scan"
        )


def _row_as_json(row: CheckpointRow) -> dict[str, object]:
    return {
        "company_id": row.company_id,
        "title_original": row.title_original,
        "location_original": row.location_original,
        "canonical_url": row.canonical_url,
        "candidate_section": row.candidate_section,
        "role": {
            "decision": row.role.decision.value,
            "reason_code": row.role.reason_code,
            "reason": row.role.reason,
            "family_id": row.role.family_id,
            "matched_term": row.role.matched_term,
        },
        "location": None
        if row.location is None
        else {
            "decision": row.location.decision.value,
            "reason_code": row.location.reason_code,
            "reason": row.location.reason,
            "matched_locations": list(row.location.matched_locations),
            "work_modes": list(row.location.work_modes),
        },
        "normalized_job": _job_as_json(row.normalized_job),
    }


def _job_as_json(job: NormalizedJob) -> dict[str, object]:
    published = job.published_at
    return {
        "schema_version": job.schema_version,
        "company_id": job.company_id,
        "source_type": job.source_type,
        "external_job_id": job.external_job_id,
        "title_original": job.title_original,
        "title_normalized": job.title_normalized,
        "location_original": job.location_original,
        "location_normalized": list(job.location_normalized),
        # Discriminated so the date/datetime distinction survives the round trip. Some
        # adapters report a bare date and the lifecycle code treats the two differently.
        "published_at": None if published is None else published.isoformat(),
        "published_at_is_date": published is not None and not isinstance(published, datetime),
        "published_at_raw": job.published_at_raw,
        "date_basis": job.date_basis.value,
        "canonical_url": job.canonical_url,
        # Descriptions ARE stored, despite being the bulk of the payload (~23kB each).
        # Dropping them looked like a cheap saving, but roughly a third of listings carry
        # the description inline; omitting it forces the resumed run to make an HTTP
        # request the original never needed, which can fail and send the row to review
        # instead of the model. Correctness over disk: the file is ~30MB at worst.
        "description": job.description,
        "description_hash": job.description_hash,
        "source_metadata": dict(job.source_metadata),
    }


def _row_from_json(entry: object, index: int) -> CheckpointRow:
    if not isinstance(entry, dict):
        raise CheckpointError(f"checkpoint row {index} is not an object")
    try:
        return CheckpointRow(
            company_id=required_string(entry, "company_id"),
            title_original=required_string(entry, "title_original"),
            location_original=required_string(entry, "location_original"),
            canonical_url=required_string(entry, "canonical_url"),
            candidate_section=required_string(entry, "candidate_section"),
            role=_role_from_json(entry.get("role"), index),
            location=_location_from_json(entry.get("location"), index),
            normalized_job=_job_from_json(entry.get("normalized_job"), index),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CheckpointError(f"checkpoint row {index} is malformed: {error}") from error


def _role_from_json(raw: object, index: int) -> RoleFilterResult:
    if not isinstance(raw, dict):
        raise CheckpointError(f"checkpoint row {index} has no role decision")
    return RoleFilterResult(
        decision=RoleDecision(required_string(raw, "decision")),
        reason_code=required_string(raw, "reason_code"),
        reason=required_string(raw, "reason"),
        family_id=optional_string(raw, "family_id"),
        matched_term=optional_string(raw, "matched_term"),
    )


def _location_from_json(raw: object, index: int) -> LocationFilterResult | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise CheckpointError(f"checkpoint row {index} has a malformed location decision")
    return LocationFilterResult(
        decision=LocationDecision(required_string(raw, "decision")),
        reason_code=required_string(raw, "reason_code"),
        reason=required_string(raw, "reason"),
        matched_locations=tuple(_string_sequence(raw.get("matched_locations"))),
        work_modes=tuple(_string_sequence(raw.get("work_modes"))),
    )


def _job_from_json(raw: object, index: int) -> NormalizedJob:
    if not isinstance(raw, dict):
        raise CheckpointError(f"checkpoint row {index} has no normalized job")
    published_raw = raw.get("published_at")
    published: datetime | Any = None
    if isinstance(published_raw, str):
        published = datetime.fromisoformat(published_raw)
        if raw.get("published_at_is_date"):
            published = published.date()
    metadata = raw.get("source_metadata")
    return NormalizedJob(
        schema_version=int(raw.get("schema_version") or 0),
        company_id=required_string(raw, "company_id"),
        source_type=required_string(raw, "source_type"),
        external_job_id=optional_string(raw, "external_job_id"),
        title_original=required_string(raw, "title_original"),
        title_normalized=required_string(raw, "title_normalized"),
        location_original=required_string(raw, "location_original"),
        location_normalized=tuple(_string_sequence(raw.get("location_normalized"))),
        published_at=published,
        published_at_raw=optional_string(raw, "published_at_raw"),
        date_basis=DateBasis(required_string(raw, "date_basis")),
        canonical_url=required_string(raw, "canonical_url"),
        description=optional_string(raw, "description"),
        description_hash=optional_string(raw, "description_hash"),
        source_metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
    )


def _string_sequence(value: object) -> Sequence[str]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise CheckpointError("expected a list of strings")
    return [str(item) for item in value]
