"""Durable provider boundary: replay returned responses and retain all request spending."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import uuid4

from job_finder.cost import TokenRates
from job_finder.matching.evaluator import (
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    ModelPolicy,
    SeniorityLLMClient,
)
from job_finder.persistence.batches import encode


def fingerprint(value: object) -> str:
    return sha256(encode(value).encode("utf-8")).hexdigest()


class JournalClient:
    """One instance per invocation; candidate context owns ordered replay responses."""

    def __init__(
        self,
        client: SeniorityLLMClient,
        connection: sqlite3.Connection,
        *,
        attempt_id: str,
        batch_date: str,
        rates: TokenRates | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.client = client
        self.connection = connection
        self.attempt_id = attempt_id
        self.batch_date = batch_date
        self.rates = rates
        self.clock = clock
        self.ordinal = -1
        self.replies: list[sqlite3.Row] = []
        # A previous process might have died after the provider charged it. Unknown is
        # honest; claiming zero or silently replaying a nonexistent response is not.
        self.connection.execute(
            "UPDATE llm_requests SET state = 'unknown' WHERE attempt_id = ? AND state = 'inflight'",
            (attempt_id,),
        )

    def begin_candidate(self, ordinal: int) -> None:
        self.ordinal = ordinal
        self.replies = self.connection.execute(
            "SELECT * FROM llm_requests WHERE attempt_id = ? AND ordinal = ? "
            "AND state = 'returned' ORDER BY rowid",
            (self.attempt_id, ordinal),
        ).fetchall()

    def complete(self, request: LLMRequest, policy: ModelPolicy) -> LLMResponse:
        request_hash = fingerprint({"request": asdict(request), "policy": policy.cache_key})
        if self.replies:
            reply = self.replies.pop(0)
            if reply["fingerprint"] != request_hash:
                raise ValueError("saved response does not match the current evaluation request")
            return LLMResponse(**json.loads(reply["response_json"]))
        request_id = uuid4().hex
        self.connection.execute(
            "INSERT INTO llm_requests(request_id, attempt_id, batch_date, requested_at, ordinal, "
            "fingerprint, state, model_policy, rates_json) "
            "VALUES (?, ?, ?, ?, ?, ?, 'inflight', ?, ?)",
            (
                request_id,
                self.attempt_id,
                self.batch_date,
                self.clock().isoformat(),
                self.ordinal,
                request_hash,
                policy.cache_key,
                None if self.rates is None else encode(asdict(self.rates)),
            ),
        )
        try:
            response = self.client.complete(request, policy)
        except LLMProviderError as error:
            if error.response is None:
                self.connection.execute(
                    "UPDATE llm_requests SET state = 'unknown' WHERE request_id = ?", (request_id,)
                )
                raise
            response = error.response
        # Autocommit this staging write before validators or candidate commits run.
        self.connection.execute(
            "UPDATE llm_requests SET state = 'returned', response_json = ?, "
            "input_tokens = ?, output_tokens = ? WHERE request_id = ?",
            (encode(asdict(response)), response.input_tokens, response.output_tokens, request_id),
        )
        return response

    def usage(self) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0) "
            "FROM llm_requests WHERE attempt_id = ?",
            (self.attempt_id,),
        ).fetchone()
        return {
            "request_count": row[0],
            "estimated_input_tokens": 0,
            "measured_input_tokens": row[1],
            "measured_output_tokens": row[2],
        }
