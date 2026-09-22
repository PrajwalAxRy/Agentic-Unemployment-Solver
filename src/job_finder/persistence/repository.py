"""Transactional repository for observed jobs and evaluation state."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast

from job_finder.core.job_contracts import NormalizedJob
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
                invalidate = (
                    str(existing["profile_version"]) != version
                    or str(existing["evaluation_status"]) != EvaluationStatus.COMPLETED
                )
                self._connection.execute(
                    """
                    UPDATE jobs SET
                        external_job_id = ?, canonical_url = ?, fallback_fingerprint = ?,
                        last_seen_at = ?, profile_version = ?,
                        prompt_version = CASE WHEN ? THEN NULL ELSE prompt_version END,
                        model_policy = CASE WHEN ? THEN NULL ELSE model_policy END,
                        evaluation_status = CASE WHEN ? THEN 'pending' ELSE evaluation_status END,
                        seniority_result_json = CASE
                            WHEN ? THEN NULL ELSE seniority_result_json END,
                        updated_at = ?
                    WHERE job_key = ?
                    """,
                    (
                        job.external_job_id,
                        identity.canonical_url,
                        identity.fallback_fingerprint,
                        observed_text,
                        version,
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
            needs_evaluation=record.evaluation_status is not EvaluationStatus.COMPLETED,
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
                self._connection.execute(
                    """
                    UPDATE jobs SET
                        description_hash = ?, profile_version = ?, prompt_version = ?,
                        model_policy = ?,
                        evaluation_status = 'pending', seniority_result_json = NULL,
                        updated_at = ?
                    WHERE job_key = ?
                    """,
                    (job.description_hash, version, prompt, policy, now, identity.job_key),
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
        try:
            result_json = json.dumps(
                result,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError) as error:
            raise ValueError("seniority result must be JSON-compatible") from error
        if not isinstance(json.loads(result_json), dict):
            raise ValueError("seniority result must be a JSON object")

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
        external_job_id=(
            str(row["external_job_id"]) if row["external_job_id"] is not None else None
        ),
        canonical_url=str(row["canonical_url"]),
        fallback_fingerprint=str(row["fallback_fingerprint"]),
        first_seen_at=_parse_timestamp(str(row["first_seen_at"])),
        last_seen_at=_parse_timestamp(str(row["last_seen_at"])),
        description_hash=(
            str(row["description_hash"]) if row["description_hash"] is not None else None
        ),
        profile_version=str(row["profile_version"]),
        prompt_version=(str(row["prompt_version"]) if row["prompt_version"] is not None else None),
        model_policy=(str(row["model_policy"]) if row["model_policy"] is not None else None),
        evaluation_status=EvaluationStatus(str(row["evaluation_status"])),
        seniority_result=result,
    )


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
