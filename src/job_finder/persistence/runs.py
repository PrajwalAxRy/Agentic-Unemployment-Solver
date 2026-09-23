"""Transactional persistence for sanitized manual-scan run metrics."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast


class ScanRunStatus(StrEnum):
    """Durable lifecycle and coverage outcome for one manual scan."""

    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ScanRunRecord:
    """Version identities and aggregate metrics retained for one scan."""

    run_id: str
    started_at: datetime
    completed_at: datetime | None
    status: ScanRunStatus
    registry_version: str
    profile_version: str
    prompt_version: str
    model_policy: str
    metrics: Mapping[str, object] | None


class ScanRunRepository:
    """Create and finish scan runs without storing job descriptions or secrets."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def start(
        self,
        run_id: str,
        *,
        started_at: datetime,
        registry_version: str,
        profile_version: str,
        prompt_version: str,
        model_policy: str,
    ) -> ScanRunRecord:
        """Insert one running record before external source work begins."""
        values = tuple(
            _required_text(value, name)
            for value, name in (
                (run_id, "run_id"),
                (registry_version, "registry_version"),
                (profile_version, "profile_version"),
                (prompt_version, "prompt_version"),
                (model_policy, "model_policy"),
            )
        )
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._connection.execute(
                """
                INSERT INTO scan_runs (
                    run_id, started_at, completed_at, status, registry_version,
                    profile_version, prompt_version, model_policy, metrics_json
                ) VALUES (?, ?, NULL, 'running', ?, ?, ?, ?, NULL)
                """,
                (
                    values[0],
                    _timestamp_text(started_at),
                    values[1],
                    values[2],
                    values[3],
                    values[4],
                ),
            )
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise
        return self.require(values[0])

    def finish(
        self,
        run_id: str,
        *,
        completed_at: datetime,
        status: ScanRunStatus,
        metrics: Mapping[str, object],
    ) -> ScanRunRecord:
        """Finish a running record with aggregate JSON-safe metrics."""
        key = _required_text(run_id, "run_id")
        if status is ScanRunStatus.RUNNING:
            raise ValueError("finished scan status cannot be running")
        try:
            metrics_json = json.dumps(
                metrics,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError) as error:
            raise ValueError("scan metrics must be JSON-compatible") from error
        if not isinstance(json.loads(metrics_json), dict):
            raise ValueError("scan metrics must be a JSON object")

        self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._select(key)
            if existing is None:
                raise KeyError(f"unknown scan run: {key}")
            if existing["status"] != ScanRunStatus.RUNNING:
                raise ValueError("only a running scan can be finished")
            started_at = _parse_timestamp(str(existing["started_at"]))
            if completed_at.astimezone(UTC) < started_at:
                raise ValueError("scan completed_at cannot precede started_at")
            self._connection.execute(
                """
                UPDATE scan_runs
                SET completed_at = ?, status = ?, metrics_json = ?
                WHERE run_id = ?
                """,
                (_timestamp_text(completed_at), status.value, metrics_json, key),
            )
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise
        return self.require(key)

    def get(self, run_id: str) -> ScanRunRecord | None:
        """Return one run by ID."""
        row = self._select(run_id)
        return _record_from_row(row) if row is not None else None

    def require(self, run_id: str) -> ScanRunRecord:
        """Return one run or raise for an unknown ID."""
        record = self.get(run_id)
        if record is None:
            raise KeyError(f"unknown scan run: {run_id}")
        return record

    def _select(self, run_id: str) -> sqlite3.Row | None:
        return cast(
            sqlite3.Row | None,
            self._connection.execute(
                "SELECT * FROM scan_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone(),
        )


def _record_from_row(row: sqlite3.Row) -> ScanRunRecord:
    metrics_raw = row["metrics_json"]
    metrics: Mapping[str, object] | None = None
    if metrics_raw is not None:
        parsed = json.loads(str(metrics_raw))
        if not isinstance(parsed, dict):
            raise ValueError("stored scan metrics must be a JSON object")
        metrics = parsed
    return ScanRunRecord(
        run_id=str(row["run_id"]),
        started_at=_parse_timestamp(str(row["started_at"])),
        completed_at=(
            _parse_timestamp(str(row["completed_at"])) if row["completed_at"] is not None else None
        ),
        status=ScanRunStatus(str(row["status"])),
        registry_version=str(row["registry_version"]),
        profile_version=str(row["profile_version"]),
        prompt_version=str(row["prompt_version"]),
        model_policy=str(row["model_policy"]),
        metrics=metrics,
    )


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
