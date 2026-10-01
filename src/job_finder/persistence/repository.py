"""Transactional repository for observed jobs and evaluation state."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import cast

from job_finder.core.job_contracts import NormalizedJob
from job_finder.core.lifecycle import JobLifecycleState
from job_finder.persistence.identity import job_identity


class EvaluationStatus(StrEnum):
    """Durable evaluation lifecycle states."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class JobRecord:
    """Persisted state for one stable job identity."""

    job_key: str
    company_id: str
    source_type: str
    external_job_id: str | None
    canonical_url: str
    fallback_fingerprint: str
    first_seen_at: datetime
    last_seen_at: datetime
    description_hash: str | None
    profile_version: str
    prompt_version: str | None
    model_policy: str | None
    evaluation_status: EvaluationStatus
    seniority_result: Mapping[str, object] | None
    # Lifecycle state (to_change.md 4.1). Stored as current state, not history (4.2):
    # with a 3-absence close rule any gap a job survives is <= 2 days, so the overwritten
    # history is bounded and small.
    status: str = "active"
    closed_at: date | None = None
    consecutive_absences: int = 0
    probe_state: str | None = None
    live_but_missing_days: int = 0
    sighting_count: int = 0
    verdict: str | None = None
    verdict_at: datetime | None = None
    required_experience: str | None = None
    # Migration 5. The description is the only large field here and is nulled by
    # `state prune` once a job goes stale; everything below is short model output that was
    # previously discarded. All default to None because old rows genuinely lack them and
    # cannot be backfilled -- the text no longer exists.
    description: str | None = None
    relevance_evidence: str | None = None
    relevance_reason: str | None = None
    # NULL here means the deterministic filter resolved the location so the model was never
    # asked, which is the common case -- not that it was asked and declined to answer.
    location_evidence: str | None = None
    location_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ObservationResult:
    """Result of recording a filtered listing before expensive work."""

    record: JobRecord
    is_new: bool
    needs_evaluation: bool


@dataclass(frozen=True, slots=True)
class EvaluationPreparation:
    """Whether a detailed job needs an LLM request or can reuse a cached result."""

    record: JobRecord
    needs_evaluation: bool


class JobStateRepository:
    """SQLite-backed job state with explicit transactional transitions."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def observe_listing(
        self,
        job: NormalizedJob,
        *,
        observed_at: datetime,
        profile_version: str,
    ) -> ObservationResult:
        """Persist observation before description retrieval or LLM evaluation."""
        observed_text = _timestamp_text(observed_at)
        version = _required_text(profile_version, "profile_version")
        identity = job_identity(job)
        now = _utc_now_text()

        self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._select(identity.job_key)
            if existing is None:
                self._connection.execute(
                    """
                    INSERT INTO jobs (
                        job_key, company_id, source_type, external_job_id, canonical_url,
                        fallback_fingerprint, first_seen_at, last_seen_at, description_hash,
                        profile_version, prompt_version, evaluation_status,
                        seniority_result_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'pending', NULL, ?, ?)
                    """,
                    (
                        identity.job_key,
                        job.company_id,
                        job.source_type,
                        job.external_job_id,
                        identity.canonical_url,
                        identity.fallback_fingerprint,
                        observed_text,
                        observed_text,
                        job.description_hash,
                        version,
                        now,
                        now,
                    ),
                )
                is_new = True
            else:
                _ensure_same_source(existing, job)
                first_seen_at = _parse_timestamp(str(existing["first_seen_at"]))
                if observed_at.astimezone(UTC) < first_seen_at:
                    raise ValueError("observed_at cannot precede a job's first_seen_at")
                invalidate = str(existing["profile_version"]) != version or (
                    job.description_hash is not None
                    and existing["description_hash"] != job.description_hash
                )
                self._connection.execute(
                    """
                    UPDATE jobs SET
                        external_job_id = ?, canonical_url = ?, fallback_fingerprint = ?,
                        last_seen_at = ?, description_hash = COALESCE(?, description_hash),
                        profile_version = ?,
                        prompt_version = CASE WHEN ? THEN NULL ELSE prompt_version END,
                        model_policy = CASE WHEN ? THEN NULL ELSE model_policy END,
                        evaluation_status = CASE WHEN ? THEN 'pending' ELSE evaluation_status END,
                        seniority_result_json = CASE
                            WHEN ? THEN NULL ELSE seniority_result_json END,
                        -- A changed description_hash means the stored text is stale. Keeping
                        -- it would leave the database disagreeing with the hash beside it,
                        -- and prepare_evaluation rewrites it from the fresh fetch anyway.
                        description = CASE WHEN ? THEN NULL ELSE description END,
                        updated_at = ?
                    WHERE job_key = ?
                    """,
                    (
                        job.external_job_id,
                        identity.canonical_url,
                        identity.fallback_fingerprint,
                        observed_text,
                        job.description_hash,
                        version,
                        invalidate,
                        invalidate,
                        invalidate,
                        invalidate,
                        invalidate,
                        now,
                        identity.job_key,
                    ),
                )
                is_new = False
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise

        record = self.require(identity.job_key)
        return ObservationResult(
            record=record,
            is_new=is_new,
            needs_evaluation=record.evaluation_status is EvaluationStatus.PENDING,
        )

    def prepare_evaluation(
        self,
        job: NormalizedJob,
        *,
        profile_version: str,
        prompt_version: str,
        model_policy: str,
    ) -> EvaluationPreparation:
        """Reuse a matching completed decision or atomically mark the job pending."""
        if job.description is None or job.description_hash is None:
            raise ValueError("evaluation preparation requires a description and description_hash")
        version = _required_text(profile_version, "profile_version")
        prompt = _required_text(prompt_version, "prompt_version")
        policy = _required_text(model_policy, "model_policy")
        identity = job_identity(job)
        now = _utc_now_text()

        self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._select(identity.job_key)
            if existing is None:
                raise KeyError(f"job must be observed before evaluation: {identity.job_key}")
            _ensure_same_source(existing, job)
            reusable = (
                str(existing["evaluation_status"]) == EvaluationStatus.COMPLETED
                and existing["description_hash"] == job.description_hash
                and existing["profile_version"] == version
                and existing["prompt_version"] == prompt
                and existing["model_policy"] == policy
            )
            if not reusable:
                # The description is stored here rather than in observe_listing on purpose:
                # this is the only point that every job passes through *and* that is already
                # scoped to jobs actually reaching the model. Writing it at observation
                # would persist all ~42,000 listings instead of the ~3,677 retained ones.
                self._connection.execute(
                    """
                    UPDATE jobs SET
                        description = ?, description_hash = ?,
                        profile_version = ?, prompt_version = ?,
                        model_policy = ?,
                        evaluation_status = 'pending', seniority_result_json = NULL,
                        updated_at = ?
                    WHERE job_key = ?
                    """,
                    (
                        job.description,
                        job.description_hash,
                        version,
                        prompt,
                        policy,
                        now,
                        identity.job_key,
                    ),
                )
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise

        record = self.require(identity.job_key)
        return EvaluationPreparation(record=record, needs_evaluation=not reusable)

    def complete_evaluation(
        self,
        job_key: str,
        result: Mapping[str, object],
    ) -> JobRecord:
        """Atomically complete a pending evaluation with JSON-safe structured output."""
        key = _required_text(job_key, "job_key")
        result_json = _json_object(result, "seniority result")

        self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._select(key)
            if existing is None:
                raise KeyError(f"unknown job_key: {key}")
            if existing["evaluation_status"] != EvaluationStatus.PENDING:
                raise ValueError("only a pending evaluation can be completed")
            if (
                existing["description_hash"] is None
                or existing["prompt_version"] is None
                or existing["model_policy"] is None
            ):
                raise ValueError(
                    "pending evaluation is missing description, prompt version, or model policy"
                )
            self._connection.execute(
                """
                UPDATE jobs SET evaluation_status = 'completed',
                    seniority_result_json = ?, updated_at = ?
                WHERE job_key = ?
                """,
                (result_json, _utc_now_text(), key),
            )
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise
        return self.require(key)

    def fail_evaluation(
        self,
        job_key: str,
        result: Mapping[str, object],
    ) -> JobRecord:
        """Persist a terminal non-match or manual-review result until inputs change."""
        key = _required_text(job_key, "job_key")
        result_json = _json_object(result, "evaluation failure result")
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._select(key)
            if existing is None:
                raise KeyError(f"unknown job_key: {key}")
            if existing["evaluation_status"] != EvaluationStatus.PENDING:
                raise ValueError("only a pending evaluation can fail")
            self._connection.execute(
                """
                UPDATE jobs SET evaluation_status = 'failed',
                    seniority_result_json = ?, updated_at = ?
                WHERE job_key = ?
                """,
                (result_json, _utc_now_text(), key),
            )
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise
        return self.require(key)

    def record_lifecycle(
        self,
        job_key: str,
        state: JobLifecycleState,
    ) -> JobRecord:
        """Persist one job's lifecycle state (to_change.md 4.1, 4.2).

        Written as current state rather than appended history. 4.2 justifies this: with a
        3-absence close rule, any gap a job survives is at most two days, so what gets
        overwritten is bounded and small -- noise at this granularity.
        """
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._connection.execute(
                """
                UPDATE jobs SET
                    status = ?, closed_at = ?, consecutive_absences = ?,
                    probe_state = ?, live_but_missing_days = ?, sighting_count = ?,
                    updated_at = ?
                WHERE job_key = ?
                """,
                (
                    state.status.value,
                    state.closed_at.isoformat() if state.closed_at else None,
                    state.consecutive_absences,
                    state.probe_state,
                    state.live_but_missing_days,
                    state.sighting_count,
                    _utc_now_text(),
                    job_key,
                ),
            )
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise
        return self.require(job_key)

    def record_verdict(
        self,
        job_key: str,
        *,
        verdict: str,
        verdict_at: datetime,
        required_experience: str | None = None,
        relevance_evidence: str | None = None,
        relevance_reason: str | None = None,
        location_evidence: str | None = None,
        location_reason: str | None = None,
    ) -> JobRecord:
        """Record the first time a job reached a qualifying verdict (3.6).

        Set once and never overwritten. 3.6 is explicit about why: the feed sorts on
        verdict_at, not on first sighting. Rows stranded by the normalization bug carry
        old first_seen_at values, so keying the feed on first sighting would mean the ~78
        recovered Google roles never appear as new.

        The evidence arguments are the model's verbatim quote and reasoning for the
        relevance and location judgments. They are COALESCEd like required_experience, so
        a later call that omits them preserves what is stored -- the location pair is
        genuinely absent whenever the deterministic filter resolved the location itself,
        and that must not erase evidence from a run where the model was asked.
        """
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._connection.execute(
                """
                UPDATE jobs SET
                    verdict = ?,
                    verdict_at = COALESCE(verdict_at, ?),
                    required_experience = COALESCE(?, required_experience),
                    relevance_evidence = COALESCE(?, relevance_evidence),
                    relevance_reason = COALESCE(?, relevance_reason),
                    location_evidence = COALESCE(?, location_evidence),
                    location_reason = COALESCE(?, location_reason),
                    updated_at = ?
                WHERE job_key = ?
                """,
                (
                    verdict,
                    verdict_at.isoformat(),
                    required_experience,
                    relevance_evidence,
                    relevance_reason,
                    location_evidence,
                    location_reason,
                    _utc_now_text(),
                    job_key,
                ),
            )
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise
        return self.require(job_key)

    def active_jobs_for_company(self, company_id: str) -> tuple[JobRecord, ...]:
        """Every job still open for one company, for absence detection (3.2)."""
        rows = self._connection.execute(
            "SELECT * FROM jobs WHERE company_id = ? AND status = 'active' ORDER BY job_key",
            (company_id,),
        ).fetchall()
        return tuple(_record_from_row(row) for row in rows)

    def get(self, job_key: str) -> JobRecord | None:
        """Return a record by stable job key."""
        row = self._select(job_key)
        return _record_from_row(row) if row is not None else None

    def require(self, job_key: str) -> JobRecord:
        """Return a record or raise for an unknown key."""
        record = self.get(job_key)
        if record is None:
            raise KeyError(f"unknown job_key: {job_key}")
        return record

    def list_pending(self) -> tuple[JobRecord, ...]:
        """List durable pending evaluations in first-seen order for retry."""
        rows = self._connection.execute(
            """
            SELECT * FROM jobs WHERE evaluation_status = 'pending'
            ORDER BY first_seen_at, job_key
            """
        ).fetchall()
        return tuple(_record_from_row(row) for row in rows)

    def count(self) -> int:
        """Return the number of stable identities in the store."""
        row = self._connection.execute("SELECT COUNT(*) FROM jobs").fetchone()
        return int(row[0]) if row is not None else 0

    def _select(self, job_key: str) -> sqlite3.Row | None:
        return cast(
            sqlite3.Row | None,
            self._connection.execute(
                "SELECT * FROM jobs WHERE job_key = ?",
                (job_key,),
            ).fetchone(),
        )


def _record_from_row(row: sqlite3.Row) -> JobRecord:
    result_raw = row["seniority_result_json"]
    result: Mapping[str, object] | None = None
    if result_raw is not None:
        parsed = json.loads(str(result_raw))
        if not isinstance(parsed, dict):
            raise ValueError("stored seniority result must be a JSON object")
        result = parsed
    return JobRecord(
        job_key=str(row["job_key"]),
        company_id=str(row["company_id"]),
        source_type=str(row["source_type"]),
        external_job_id=_optional_text(row["external_job_id"]),
        canonical_url=str(row["canonical_url"]),
        fallback_fingerprint=str(row["fallback_fingerprint"]),
        first_seen_at=_parse_timestamp(str(row["first_seen_at"])),
        last_seen_at=_parse_timestamp(str(row["last_seen_at"])),
        description_hash=_optional_text(row["description_hash"]),
        profile_version=str(row["profile_version"]),
        prompt_version=_optional_text(row["prompt_version"]),
        model_policy=_optional_text(row["model_policy"]),
        evaluation_status=EvaluationStatus(str(row["evaluation_status"])),
        seniority_result=result,
        status=str(row["status"]),
        closed_at=_optional_date(row["closed_at"]),
        consecutive_absences=int(row["consecutive_absences"]),
        probe_state=_optional_text(row["probe_state"]),
        live_but_missing_days=int(row["live_but_missing_days"]),
        sighting_count=int(row["sighting_count"]),
        verdict=_optional_text(row["verdict"]),
        verdict_at=_optional_timestamp(row["verdict_at"]),
        required_experience=_optional_text(row["required_experience"]),
        description=_optional_text(row["description"]),
        relevance_evidence=_optional_text(row["relevance_evidence"]),
        relevance_reason=_optional_text(row["relevance_reason"]),
        location_evidence=_optional_text(row["location_evidence"]),
        location_reason=_optional_text(row["location_reason"]),
    )


def _optional_text(value: object) -> str | None:
    return str(value) if value is not None else None


def _optional_timestamp(value: object) -> datetime | None:
    return _parse_timestamp(str(value)) if value is not None else None


def _optional_date(value: object) -> date | None:
    """closed_at is a calendar date, not an instant.

    4.2a: the lifecycle works in whole days, and the displayed closing date is last_seen
    rather than closed_at anyway -- closed_at lags by up to the absence threshold and is
    kept only as an operational record of when detection happened.
    """
    return date.fromisoformat(str(value)) if value is not None else None


def _ensure_same_source(row: sqlite3.Row, job: NormalizedJob) -> None:
    if row["company_id"] != job.company_id or row["source_type"] != job.source_type:
        raise ValueError("job identity collision across company or source")


def _required_text(value: str, path: str) -> str:
    if not value.strip():
        raise ValueError(f"{path} must be non-empty")
    return value.strip()


def _timestamp_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("stored timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def _utc_now_text() -> str:
    return datetime.now(UTC).isoformat()


def _json_object(result: Mapping[str, object], path: str) -> str:
    try:
        result_json = json.dumps(
            result,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"{path} must be JSON-compatible") from error
    if not isinstance(json.loads(result_json), dict):
        raise ValueError(f"{path} must be a JSON object")
    return result_json
