"""Tests for per-run LLM cost accounting and the daily ledger."""

from __future__ import annotations

from pathlib import Path

import pytest

from job_finder.cost import (
    RunCost,
    append_to_ledger,
    daily_totals,
    format_cost_line,
    load_rates,
    price_run,
    read_ledger,
    summarise,
)

RATES = {
    "JOB_FINDER_LLM_INPUT_COST_PER_MTOK": "0.20",
    "JOB_FINDER_LLM_OUTPUT_COST_PER_MTOK": "1.20",
}


def make_cost(
    *,
    day: str = "2026-10-01",
    evaluated: int = 100,
    priced: bool = True,
    db_bytes_before: int = 0,
    db_bytes_total: int = 0,
) -> RunCost:
    return price_run(
        run_id=f"scan-{day}",
        completed_at=f"{day}T06:00:00+00:00",
        model_policy="amd-llm-gateway:gpt-5.6-luna:v1",
        prompt_version="1.0.0",
        evaluated=evaluated,
        cache_hits=0,
        request_count=evaluated,
        input_tokens=evaluated * 7143,
        output_tokens=evaluated * 300,
        rates=load_rates(RATES) if priced else None,
        db_bytes_before=db_bytes_before,
        db_bytes_total=db_bytes_total,
    )


def test_cost_matches_the_measured_token_counts() -> None:
    """The 2026-09-30 run: 140 jobs at the measured 7,143 in / 300 out."""
    cost = make_cost(evaluated=140)

    # 140 * 7143 / 1e6 * 0.20 = 0.2000; 140 * 300 / 1e6 * 1.20 = 0.0504
    assert cost.total_cost == pytest.approx(0.2504, abs=1e-4)
    assert cost.per_evaluated_job == pytest.approx(0.00179, abs=1e-5)


def test_missing_rates_report_unknown_rather_than_zero() -> None:
    """A free run and an unpriceable run must not look identical."""
    cost = make_cost(priced=False)

    assert cost.total_cost is None
    assert not cost.priced
    assert cost.per_evaluated_job is None
    assert "unavailable" in format_cost_line(cost)
    assert "0.00" not in format_cost_line(cost)


def test_half_configured_rates_are_refused() -> None:
    """Pricing input but not output would silently under-report every single run."""
    assert load_rates({"JOB_FINDER_LLM_INPUT_COST_PER_MTOK": "0.20"}) is None
    assert load_rates({"JOB_FINDER_LLM_OUTPUT_COST_PER_MTOK": "1.20"}) is None


def test_a_bad_rate_is_an_error_not_a_silent_zero() -> None:
    with pytest.raises(ValueError, match="must be a number"):
        load_rates({**RATES, "JOB_FINDER_LLM_INPUT_COST_PER_MTOK": "cheap"})


def test_the_ledger_appends_and_survives_a_corrupt_line(tmp_path: Path) -> None:
    """One half-written entry from a killed process must not hide the whole history."""
    ledger = tmp_path / "llm_costs.jsonl"
    append_to_ledger(make_cost(day="2026-10-01"), ledger)
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write('{"run_id": "truncated"\n')
    append_to_ledger(make_cost(day="2026-10-02"), ledger)

    history = read_ledger(ledger)

    assert len(history) == 2, "the readable entries either side must both survive"
    assert [item.completed_at[:10] for item in history] == ["2026-10-01", "2026-10-02"]


def test_daily_totals_group_multiple_runs_in_one_day(tmp_path: Path) -> None:
    history = [
        make_cost(day="2026-10-01", evaluated=100),
        make_cost(day="2026-10-01", evaluated=50),
        make_cost(day="2026-10-02", evaluated=20),
    ]

    rows = daily_totals(history)

    assert [row["day"] for row in rows] == ["2026-10-01", "2026-10-02"], "oldest first"
    assert rows[0]["runs"] == 2
    assert rows[0]["evaluated"] == 150


def test_unpriced_runs_are_excluded_from_totals_but_reported(tmp_path: Path) -> None:
    """A partly-configured history must not quietly understate what was spent."""
    history = [make_cost(evaluated=100), make_cost(evaluated=100, priced=False)]

    totals = summarise(history)

    assert totals["runs"] == 2
    assert totals["priced_runs"] == 1
    assert totals["unpriced_runs"] == 1
    assert totals["total_evaluated"] == 100, "only the priced run contributes"


def test_an_absent_ledger_is_empty_not_an_error(tmp_path: Path) -> None:
    assert read_ledger(tmp_path / "never_written.jsonl") == []


def test_a_ledger_written_before_size_accounting_still_loads(tmp_path: Path) -> None:
    """The ledger is append-only, so pre-existing lines are permanent.

    They have no db_bytes_* keys. Reading them back must report zero growth rather than
    raising -- we genuinely did not measure it then, and a crash on old history would make
    `job_finder costs` useless for everyone who ran a scan before this landed.
    """
    path = tmp_path / "legacy.jsonl"
    path.write_text(
        '{"run_id": "scan-old", "completed_at": "2026-09-30T06:00:00+00:00", '
        '"evaluated": 259, "currency": "USD", "total_cost": 0.52}\n',
        encoding="utf-8",
    )

    history = read_ledger(path)

    assert len(history) == 1
    assert history[0].db_bytes_before == 0
    assert history[0].db_bytes_total == 0
    assert history[0].db_bytes_added == 0
    assert history[0].evaluated == 259, "the fields that were recorded must survive"


def test_size_growth_survives_a_ledger_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    append_to_ledger(
        make_cost(db_bytes_before=3_715_072, db_bytes_total=12_136_448),
        path,
    )

    restored = read_ledger(path)[0]

    assert restored.db_bytes_before == 3_715_072
    assert restored.db_bytes_total == 12_136_448
    assert restored.db_bytes_added == 8_421_376


def test_a_shrunken_database_reports_no_growth_rather_than_negative(tmp_path: Path) -> None:
    """`state prune` between runs legitimately shrinks the file.

    Reporting that as negative growth under a column headed "added" reads as a bug. The
    shrink is still visible in the running total, which is where it belongs.
    """
    cost = make_cost(db_bytes_before=90_000_000, db_bytes_total=4_000_000)

    assert cost.db_bytes_added == 0
    assert cost.db_bytes_total == 4_000_000


def test_daily_totals_sum_growth_but_take_the_latest_total(tmp_path: Path) -> None:
    """Two runs in a day add their growth; the file size is the last one, not the sum."""
    history = [
        make_cost(day="2026-10-01", db_bytes_before=1_000_000, db_bytes_total=3_000_000),
        make_cost(day="2026-10-01", db_bytes_before=3_000_000, db_bytes_total=4_000_000),
    ]

    rows = daily_totals(history)

    assert len(rows) == 1
    assert rows[0]["bytes_added"] == 3_000_000
    assert rows[0]["bytes_total"] == 4_000_000, "a size, not a quantity -- must not sum"


def test_the_cost_line_reports_size_even_without_rates() -> None:
    """Disk growth is measured from the file, so it is known whether or not rates are set."""
    line = format_cost_line(
        make_cost(priced=False, db_bytes_before=1_048_576, db_bytes_total=2_097_152)
    )

    assert "llm_cost=unavailable" in line
    assert "db=2.0 MB" in line
    assert "+1.0 MB" in line
