"""Discard markers, interrupted exports, unknown charges, and currency boundaries."""

import json
from datetime import UTC, datetime

from job_finder.accounting import export_accounting
from job_finder.cost import RunCost, daily_totals, iso_day, read_ledger
from job_finder.persistence.batches import BatchRepository
from job_finder.persistence.database import migrated_database
from tests.test_daily_storage import insert_batch


def test_discard_events_preserve_total_and_export_is_idempotent(tmp_path):
    ledger = tmp_path / "costs.jsonl"
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        insert_batch(connection)
        connection.execute(
            "UPDATE llm_requests SET rates_json = ?",
            (json.dumps({"input_per_mtok": 0.2, "output_per_mtok": 1.2, "currency": "USD"}),),
        )
        export_accounting(connection, ledger)
        export_accounting(connection, ledger)
        before = read_ledger(ledger)
        assert len(before) == 1
        BatchRepository(connection).restart("new_rules")
        export_accounting(connection, ledger)
        export_accounting(connection, ledger)
        after = read_ledger(ledger)
        assert len(after) == 1
        assert after[0].total_cost == before[0].total_cost
        assert after[0].discarded_reason == "force_reevaluate"
        assert len(ledger.read_text().splitlines()) == 2
        # Raw per-request values must survive: do not round this $0.000016 to zero.
        assert after[0].total_cost == 0.000016


def test_unknown_usage_is_not_reported_as_zero_even_with_prices(tmp_path):
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        insert_batch(connection)
        connection.execute(
            "UPDATE llm_requests SET input_tokens = NULL, output_tokens = NULL, state = 'unknown'"
        )
        export_accounting(connection, tmp_path / "costs.jsonl")
    history = read_ledger(tmp_path / "costs.jsonl")
    assert history[0].total_cost is None
    assert history[0].unknown_usage is True
    assert daily_totals(history)[0]["unknown_requests"] == 1


def test_export_recovers_from_truncated_line_and_reader_deduplicates(tmp_path):
    ledger = tmp_path / "costs.jsonl"
    ledger.write_text('{"event_type": "usage",')
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        insert_batch(connection)
        export_accounting(connection, ledger)
    assert len(read_ledger(ledger)) == 1
    lines = ledger.read_text().splitlines()
    with ledger.open("a") as stream:
        stream.write(lines[-1] + "\n")
    assert len(read_ledger(ledger)) == 1


def test_currency_groups_are_separate_and_dates_use_ist(tmp_path):
    assert iso_day(datetime(2026, 10, 1, 20, tzinfo=UTC).isoformat()) == "2026-10-02"
    events = [
        RunCost(
            "a",
            "2026-10-01T20:00:00+00:00",
            "model",
            "prompt",
            1,
            0,
            1,
            1,
            1,
            currency,
            1.0,
            1.0,
            2.0,
        )
        for currency in ("USD", "INR")
    ]
    rows = daily_totals(events)
    assert len(rows) == 2
    assert {row["currency"] for row in rows} == {"USD", "INR"}
    assert {row["day"] for row in rows} == {"2026-10-02"}


def test_status_only_marker_never_becomes_an_unpriced_run(tmp_path):
    ledger = tmp_path / "costs.jsonl"
    ledger.write_text(
        json.dumps(
            {
                "event_type": "discard",
                "event_id": "discard:id",
                "request_id": "id",
                "reason": "new_scan",
            }
        )
        + "\n"
    )
    assert read_ledger(ledger) == []


def test_costs_read_database_even_when_export_never_happened(tmp_path):
    from job_finder.accounting import read_accounting

    database = tmp_path / "jobs.sqlite3"
    ledger = tmp_path / "costs.jsonl"
    with migrated_database(database) as connection:
        insert_batch(connection)
    history = read_accounting(database, ledger)
    assert len(history) == 1
    assert not ledger.exists()
    with migrated_database(database) as connection:
        export_accounting(connection, ledger)
        BatchRepository(connection).discard("new_scan")
    history = read_accounting(database, ledger)
    assert len(history) == 1
    assert history[0].discarded_reason == "new_scan"
