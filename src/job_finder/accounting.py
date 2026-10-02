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


_BREAKDOWN_COLUMNS = ("cached_input_tokens", "cache_write_tokens", "reasoning_tokens")


def _requests(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    # read_accounting opens read-only and so cannot migrate: a database from before
    # migration 7 has no breakdown columns, which read as NULL (not recorded).
    present = {row[1] for row in connection.execute("PRAGMA table_info(llm_requests)")}
    breakdown = ", ".join(
        name if name in present else f"NULL AS {name}" for name in _BREAKDOWN_COLUMNS
    )
    return connection.execute(
        "SELECT request_id, attempt_id, batch_date, requested_at, ordinal, model_policy, "
        f"input_tokens, output_tokens, {breakdown}, rates_json, discarded_reason "
        "FROM llm_requests ORDER BY rowid"
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
        cached_input_tokens=row["cached_input_tokens"] or 0,
        cache_write_tokens=row["cache_write_tokens"] or 0,
        reasoning_tokens=row["reasoning_tokens"] or 0,
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


def usage_statistics(database: Path) -> list[dict[str, Any]]:
    """Per-model token averages and cost, from the requests SQLite still holds.

    Averages cover only requests with known usage. "Jobs" counts distinct candidates that
    sent at least one request, so cost per job includes the price of retries.
    """
    if not database.exists():
        return []
    connection = sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        if (
            connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'llm_requests'").fetchone()
            is None
        ):
            return []
        rows = _requests(connection)
    finally:
        connection.close()
    groups: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        groups.setdefault(row["model_policy"], []).append(row)
    statistics = []
    for model, group in sorted(groups.items()):
        known = [row for row in group if row["input_tokens"] is not None]
        jobs = {(row["attempt_id"], row["ordinal"]) for row in known}
        costs = [_request_cost(row) for row in known]
        priced = [cost.total_cost for cost in costs if cost.total_cost is not None]
        currencies = {cost.currency for cost in costs if cost.priced}
        reported = {
            name: [row[name] for row in known if row[name] is not None]
            for name in _BREAKDOWN_COLUMNS
        }
        # None unless every known request was priced in one currency: a partial total
        # would look authoritative while understating the spend.
        total = (
            sum(priced) if priced and len(priced) == len(known) and len(currencies) == 1 else None
        )
        statistics.append(
            {
                "model_policy": model,
                "requests": len(group),
                "unknown_usage_requests": len(group) - len(known),
                "jobs": len(jobs),
                "mean_input_tokens": _mean([row["input_tokens"] for row in known]),
                "mean_output_tokens": _mean([row["output_tokens"] for row in known]),
                # Breakdown means cover only requests whose provider reported it.
                "mean_cached_input_tokens": _mean(reported["cached_input_tokens"]),
                "mean_cache_write_tokens": _mean(reported["cache_write_tokens"]),
                "mean_reasoning_tokens": _mean(reported["reasoning_tokens"]),
                "breakdown_requests": len(reported["cached_input_tokens"]),
                "currency": next(iter(currencies)) if len(currencies) == 1 else None,
                "total_cost": total,
                "cost_per_request": total / len(known) if total is not None and known else None,
                "cost_per_job": total / len(jobs) if total is not None and jobs else None,
            }
        )
    return statistics


def _mean(values: list[int]) -> float | None:
    return sum(values) / len(values) if values else None


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
