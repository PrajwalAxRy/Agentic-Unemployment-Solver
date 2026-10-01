"""Idempotent export of permanent SQLite request spending to the append-only ledger."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

from job_finder.cost import RunCost, TokenRates, price_run, read_ledger


def export_accounting(connection: sqlite3.Connection, path: Path) -> None:
    """Recover missing exports after failure without repeating any provider request."""
    seen: set[str] = set()
    if path.exists():
        for line in path.read_text("utf-8").splitlines():
            try:
                value = json.loads(line)
                if isinstance(value, dict) and isinstance(value.get("event_id"), str):
                    seen.add(value["event_id"])
            except (ValueError, TypeError):
                continue
    events: list[dict[str, Any]] = []
    for row in _requests(connection):
        identifier = row["request_id"]
        if "usage:" + identifier not in seen:
            cost = _request_cost(row)
            payload = cost.as_json()
            # Round only after aggregation: rounding each cheap request can materially
            # undercount a large batch. The configured rates are preserved in SQLite.
            payload.update(
                input_cost=cost.input_cost, output_cost=cost.output_cost, total_cost=cost.total_cost
            )
            events.append(
                {
                    **payload,
                    "event_type": "usage",
                    "event_id": "usage:" + identifier,
                    "request_id": identifier,
                    "batch_date": row["batch_date"],
                }
            )
        if row["discarded_reason"] and "discard:" + identifier not in seen:
            events.append(
                {
                    "event_type": "discard",
                    "event_id": "discard:" + identifier,
                    "request_id": identifier,
                    "reason": row["discarded_reason"],
                }
            )
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_separator = False
    if path.exists() and path.stat().st_size:
        with path.open("rb") as stream:
            stream.seek(-1, 2)
            needs_separator = stream.read(1) != b"\n"
    with path.open("a", encoding="utf-8") as stream:
        if needs_separator:
            stream.write("\n")
        for event in events:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        stream.flush()


def _requests(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT request_id, attempt_id, batch_date, requested_at, model_policy, "
        "input_tokens, output_tokens, rates_json, discarded_reason FROM llm_requests ORDER BY rowid"
    ).fetchall()


def _request_cost(row: sqlite3.Row) -> RunCost:
    rates = None if row["rates_json"] is None else TokenRates(**json.loads(row["rates_json"]))
    cost = price_run(
        run_id=row["attempt_id"],
        completed_at=row["requested_at"],
        model_policy=row["model_policy"],
        prompt_version="",
        evaluated=0,
        cache_hits=0,
        request_count=1,
        input_tokens=row["input_tokens"] or 0,
        output_tokens=row["output_tokens"] or 0,
        rates=rates,
    )
    unknown = row["input_tokens"] is None or row["output_tokens"] is None
    return replace(
        cost,
        input_cost=None if unknown else cost.input_cost,
        output_cost=None if unknown else cost.output_cost,
        total_cost=None if unknown else cost.total_cost,
        unknown_usage=unknown,
        request_id=row["request_id"],
        discarded_reason=row["discarded_reason"],
    )


def read_accounting(database: Path, ledger: Path) -> list[RunCost]:
    """Read live authoritative spending even when a crash prevented ledger export."""
    history = read_ledger(ledger)
    if not database.exists():
        return history
    connection = sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        if (
            connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'llm_requests'").fetchone()
            is None
        ):
            return history
        requests = {row["request_id"]: _request_cost(row) for row in _requests(connection)}
        retained = []
        for item in history:
            if item.request_id in requests:
                current = requests[item.request_id]
                # Restoring an older backup must not undo a permanent ledger marker.
                requests[item.request_id] = replace(
                    current, discarded_reason=current.discarded_reason or item.discarded_reason
                )
            else:
                retained.append(item)
        return retained + list(requests.values())
    finally:
        connection.close()
