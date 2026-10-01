"""Single current discovery batch; replaceable attempts and permanent request accounting."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import asdict, fields
from datetime import date, datetime, timedelta, timezone
from typing import Any, cast
from uuid import uuid4

from job_finder.checkpoint import (
    CheckpointError,
    _job_as_json,
    _job_from_json,
    _location_from_json,
    _role_from_json,
)
from job_finder.collection import (
    CandidateSection,
    CompanyFilterRecord,
    FilterListingRecord,
    FilterVerificationReport,
    FinalFilterDecision,
)
from job_finder.core.job_contracts import DateBasis
from job_finder.persistence.transactions import atomic

IST = timezone(timedelta(hours=5, minutes=30))


def india_date(value: datetime) -> str:
    """Business date of an aware instant; independent of Windows timezone data."""
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(IST).date().isoformat()


def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_date_json)


def _date_json(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"unsupported persisted value: {type(value).__name__}")


def listing_payload(row: FilterListingRecord) -> dict[str, Any]:
    payload = asdict(row)
    payload["normalized_job"] = _job_as_json(row.normalized_job)
    return payload


def listing_from_payload(payload: Mapping[str, Any]) -> FilterListingRecord:
    return FilterListingRecord(
        company_id=payload["company_id"],
        company_name=payload["company_name"],
        source_rank=payload["source_rank"],
        adapter_type=payload["adapter_type"],
        title_original=payload["title_original"],
        location_original=payload["location_original"],
        canonical_url=payload["canonical_url"],
        candidate_section=CandidateSection(payload["candidate_section"]),
        date_basis=DateBasis(payload["date_basis"]),
        raw_date_text=payload["raw_date_text"],
        role=_role_from_json(payload["role"], 0),
        location=_location_from_json(payload["location"], 0),
        final_decision=FinalFilterDecision(payload["final_decision"]),
        normalized_job=_job_from_json(payload["normalized_job"], 0),
    )


def filter_metadata(report: FilterVerificationReport) -> dict[str, Any]:
    """Keep aggregate coverage and small review records, not every rejected description."""
    payload = {
        field.name: getattr(report, field.name)
        for field in fields(report)
        if field.name != "listings"
    }
    payload["companies"] = [asdict(company) for company in report.companies]
    payload["reviews"] = [
        listing_payload(row)
        for row in report.listings
        if row.final_decision is FinalFilterDecision.REVIEW
    ]
    # Deterministic reviews never enter evaluation: their descriptions are unnecessary.
    for row in payload["reviews"]:
        row["normalized_job"]["description"] = None
        row["normalized_job"]["description_hash"] = None
    return payload


def restore_filter(
    metadata: Mapping[str, Any], candidates: list[sqlite3.Row]
) -> FilterVerificationReport:
    payload = dict(metadata)
    reviews = payload.pop("reviews")
    payload["companies"] = tuple(
        CompanyFilterRecord(
            **{**company, "exception_categories": tuple(company["exception_categories"])}
        )
        for company in payload["companies"]
    )
    payload["zero_retained_companies"] = tuple(payload["zero_retained_companies"])
    payload["listings"] = tuple(
        [listing_from_payload(json.loads(row["payload_json"])) for row in candidates]
        + [listing_from_payload(row) for row in reviews]
    )
    return FilterVerificationReport(**payload)


class BatchRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def discard(self, reason: str) -> None:
        """Remove current work but preserve accounting and independent job history."""
        with atomic(self.connection):
            current = self.current()
            if current is not None:
                self.connection.execute(
                    "UPDATE llm_requests SET discarded_reason = ?, response_json = NULL "
                    "WHERE attempt_id = ? AND discarded_reason IS NULL",
                    (reason, current["attempt_id"]),
                )
            self.connection.execute("DELETE FROM daily_batch")

    def current(self) -> sqlite3.Row | None:
        return cast(
            sqlite3.Row | None,
            self.connection.execute("SELECT * FROM daily_batch WHERE singleton = 1").fetchone(),
        )

    def require_fresh(self, now: datetime) -> sqlite3.Row:
        current = self.current()
        if current is None:
            raise CheckpointError(
                "no database batch; run a fresh scan (legacy file checkpoints are retired)"
            )
        if current["admission_date"] != india_date(now):
            raise CheckpointError("saved batch expired at midnight IST; run a fresh scan")
        return current

    def restart(self, evaluation_config: str) -> None:
        with atomic(self.connection):
            current = self.current()
            if current is None:
                raise CheckpointError("no saved batch")
            self.connection.execute(
                "UPDATE llm_requests SET discarded_reason = 'force_reevaluate', "
                "response_json = NULL "
                "WHERE attempt_id = ? AND discarded_reason IS NULL",
                (current["attempt_id"],),
            )
            self.connection.execute(
                "UPDATE daily_batch SET attempt_id = ?, evaluation_config = ?, force = 1",
                (uuid4().hex, evaluation_config),
            )
            self.connection.execute("UPDATE batch_candidates SET result_json = NULL")

    def candidates(self) -> list[sqlite3.Row]:
        return self.connection.execute("SELECT * FROM batch_candidates ORDER BY ordinal").fetchall()

    def cache(self, fingerprint: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT result_json FROM evaluation_cache WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        return None if row is None else json.loads(row[0])

    def finish_candidate(
        self, ordinal: int, result: Mapping[str, Any], fingerprint: str | None
    ) -> None:
        """Caller commits this with the full job judgment in one atomic transaction."""
        payload = encode(result)
        self.connection.execute(
            "UPDATE batch_candidates SET result_json = ? WHERE ordinal = ?", (payload, ordinal)
        )
        if fingerprint is not None:
            key = self.connection.execute(
                "SELECT job_key FROM batch_candidates WHERE ordinal = ?", (ordinal,)
            ).fetchone()[0]
            self.connection.execute(
                "INSERT OR REPLACE INTO evaluation_cache VALUES (?, ?, ?)",
                (fingerprint, key, payload),
            )
        current = self.current()
        if current is not None:
            self.connection.execute(
                "UPDATE llm_requests SET state = 'consumed', response_json = NULL "
                "WHERE attempt_id = ? AND ordinal = ? AND state = 'returned'",
                (current["attempt_id"], ordinal),
            )
