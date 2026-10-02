"""Cache-read, cache-write and reasoning tokens: capture, pricing and per-model averages."""

import json
import sqlite3
from types import SimpleNamespace

import pytest

from job_finder.accounting import export_accounting, read_accounting, usage_statistics
from job_finder.cost import TokenRates, load_rates, read_ledger
from job_finder.matching.evaluator import LLMRequest, LLMResponse
from job_finder.matching.journal import JournalClient
from job_finder.matching.openai_client import AmdGatewayClient, load_gateway_settings
from job_finder.persistence.database import migrated_database
from tests.matching.test_openai_client import completion, configured_environment, fake_client
from tests.test_daily_storage import insert_batch

RATES = {"input_per_mtok": 1.0, "output_per_mtok": 10.0, "currency": "USD"}


def _gateway_reply(**usage_details):
    reply = completion()
    reply.usage = SimpleNamespace(
        prompt_tokens=1000,
        completion_tokens=400,
        prompt_tokens_details=SimpleNamespace(
            cached_tokens=usage_details.get("cached", 600),
            cache_write_tokens=usage_details.get("written", 300),
        ),
        completion_tokens_details=SimpleNamespace(
            reasoning_tokens=usage_details.get("reasoning", 250)
        ),
    )
    return reply


def _complete(reply) -> LLMResponse:
    settings = load_gateway_settings(environment=configured_environment())
    client, _ = fake_client(reply)
    return AmdGatewayClient(settings, client=client).complete(
        LLMRequest("system", "user", {}, 100), settings.model_policy
    )


def test_gateway_reads_cache_and_reasoning_breakdown():
    response = _complete(_gateway_reply())
    assert (response.cached_input_tokens, response.cache_write_tokens) == (600, 300)
    assert response.reasoning_tokens == 250


def test_missing_or_implausible_breakdown_is_unknown_not_zero():
    reply = completion()  # usage carries totals only
    response = _complete(reply)
    assert response.cached_input_tokens is None
    assert response.reasoning_tokens is None
    # A subset larger than its total cannot be right; keep the totals, drop the detail.
    response = _complete(_gateway_reply(cached=5000, reasoning="many"))
    assert response.input_tokens == 1000
    assert response.cached_input_tokens is None
    assert response.reasoning_tokens is None


def test_cache_rates_price_input_subsets_and_default_to_full_rate():
    full = TokenRates(**RATES)
    assert full.input_cost_of(1000, cached_tokens=600, cache_write_tokens=300) == pytest.approx(
        0.001
    )
    split = TokenRates(**RATES, cached_input_per_mtok=0.1, cache_write_per_mtok=1.25)
    # 100 plain at 1.0 + 600 cached at 0.1 + 300 written at 1.25, per million.
    assert split.input_cost_of(1000, cached_tokens=600, cache_write_tokens=300) == pytest.approx(
        (100 + 60 + 375) / 1_000_000
    )


def test_load_rates_reads_optional_cache_rates():
    values = {
        "JOB_FINDER_LLM_INPUT_COST_PER_MTOK": "1",
        "JOB_FINDER_LLM_OUTPUT_COST_PER_MTOK": "10",
        "JOB_FINDER_LLM_CACHED_INPUT_COST_PER_MTOK": "0.1",
    }
    rates = load_rates(values)
    assert rates is not None
    assert rates.cached_input_per_mtok == 0.1
    assert rates.cache_write_per_mtok is None
    # Old rates_json rows carry no cache keys and must still load.
    assert TokenRates(**RATES).cached_input_per_mtok is None


def test_journal_records_breakdown_and_costs_price_it(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    ledger = tmp_path / "costs.jsonl"
    rates = TokenRates(**RATES, cached_input_per_mtok=0.1)
    with migrated_database(database) as connection:
        insert_batch(connection)
        connection.execute("DELETE FROM llm_requests")
        provider = SimpleNamespace(complete=lambda request, policy: _complete(_gateway_reply()))
        journal = JournalClient(
            provider, connection, attempt_id="attempt", batch_date="2026-10-01", rates=rates
        )
        settings = load_gateway_settings(environment=configured_environment())
        journal.begin_candidate(0)
        journal.complete(LLMRequest("system", "user", {}, 100), settings.model_policy)
        journal.complete(LLMRequest("system", "user", {}, 100), settings.model_policy)
        row = connection.execute(
            "SELECT cached_input_tokens, cache_write_tokens, reasoning_tokens FROM llm_requests"
        ).fetchone()
        assert tuple(row) == (600, 300, 250)
        export_accounting(connection, ledger)

    expected = (100 + 60 + 300) / 1_000_000 + 400 * 10 / 1_000_000
    exported = read_ledger(ledger)
    assert exported[0].cached_input_tokens == 600
    assert exported[0].total_cost == pytest.approx(expected)
    assert read_accounting(database, ledger)[0].total_cost == pytest.approx(expected)

    [stats] = usage_statistics(database)
    assert stats["requests"] == 2
    assert stats["jobs"] == 1  # a retry is another request for the same job
    assert stats["mean_input_tokens"] == 1000
    assert stats["mean_output_tokens"] == 400
    assert stats["mean_cached_input_tokens"] == 600
    assert stats["mean_reasoning_tokens"] == 250
    assert stats["cost_per_request"] == pytest.approx(expected)
    assert stats["cost_per_job"] == pytest.approx(2 * expected)


def test_statistics_read_a_database_from_before_the_breakdown(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    with migrated_database(database) as connection:
        insert_batch(connection)
        connection.execute("UPDATE llm_requests SET rates_json = ?", (json.dumps(RATES),))
    # Simulate schema 6: the breakdown columns do not exist yet.
    with sqlite3.connect(database) as raw:
        for column in ("cached_input_tokens", "cache_write_tokens", "reasoning_tokens"):
            raw.execute(f"ALTER TABLE llm_requests DROP COLUMN {column}")

    [stats] = usage_statistics(database)
    assert stats["mean_input_tokens"] == 20
    assert stats["mean_cached_input_tokens"] is None
    assert stats["breakdown_requests"] == 0
    assert stats["total_cost"] == pytest.approx((20 * 1.0 + 10 * 10.0) / 1_000_000)
    assert read_accounting(database, tmp_path / "costs.jsonl")[0].cached_input_tokens == 0


def test_statistics_withhold_cost_when_any_request_is_unpriced(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    with migrated_database(database) as connection:
        insert_batch(connection)  # rates_json is NULL: unpriced
    [stats] = usage_statistics(database)
    assert stats["mean_output_tokens"] == 10
    assert stats["total_cost"] is None
    assert stats["cost_per_job"] is None
