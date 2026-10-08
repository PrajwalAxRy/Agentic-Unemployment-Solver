"""Exercise durable boundaries with real evaluators, fake sources and disposable state."""

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

import job_finder.daily_scan as daily
from job_finder.adapters.base import AdapterRegistry
from job_finder.checkpoint import CheckpointError
from job_finder.core.lifecycle import JobLifecycleState
from job_finder.matching.evaluator import ModelPolicy, UsageBudget, UsageLimits
from job_finder.matching.merged_evaluator import MergedEvaluator
from job_finder.matching.merged_prompt import load_merged_prompt
from job_finder.persistence.database import migrated_database
from job_finder.persistence.identity import job_identity
from job_finder.persistence.maintenance import backup_state, restore_state
from job_finder.persistence.repository import JobStateRepository
from tests.test_merged_scan_evidence import _Client, _job, _merged_response
from tests.test_scan import (
    PROFILE,
    SCAN_AT,
    FailingLLMClient,
    StubAdapter,
    StubLLMClient,
    decision,
    evaluator,
    job,
    registry,
    source,
)

DESCRIPTION = "Build ML systems. 3+ years of experience"


def run(
    tmp_path,
    client,
    *,
    command="scan",
    listings=None,
    adapter=None,
    model=None,
    profile=PROFILE,
    **kwargs,
):
    adapter = adapter or StubAdapter(
        {
            "healthy": listings
            if listings is not None
            else (job("healthy", "1", "ML Engineer", DESCRIPTION),)
        }
    )
    return daily.run_daily_scan(
        registry(source("healthy")),
        AdapterRegistry([adapter]),
        profile,
        model or evaluator(client),
        database_path=tmp_path / "jobs.sqlite3",
        lock_path=tmp_path / "scan.lock",
        command=command,
        scan_at=SCAN_AT,
        source_retry_count=0,
        clock=lambda: SCAN_AT,
        **kwargs,
    )


class NoWebsiteAdapter(StubAdapter):
    def list_jobs(self, company_source):
        raise AssertionError("evaluation must not visit a job website")


def test_discovery_only_freezes_full_descriptions_without_cache_or_provider_work(tmp_path):
    from tests.test_scan import RetryingDetailAdapter

    known = job("healthy", "1", "ML Engineer", DESCRIPTION)
    run(tmp_path, StubLLMClient([decision(True)]), listings=(known,))
    new = job("healthy", "2", "ML Engineer", DESCRIPTION + " New posting.")
    adapter = RetryingDetailAdapter(
        {
            "healthy": tuple(
                replace(row, description=None, description_hash=None) for row in (known, new)
            )
        },
        details={"1": known, "2": new},
        failures_remaining=0,
    )
    client = StubLLMClient([])
    saved = run(tmp_path, client, adapter=adapter, discovery_only=True)
    assert adapter.detail_requests == 2
    assert not client.requests
    assert saved.exit_code == 0
    assert saved.pending_count == 2
    assert saved.halt_reason == "discovery_only"
    assert not saved.report.evaluation_complete
    assert saved.report.usage.request_count == 0
    assert saved.report.metrics.llm_budget_halted_count == 0
    assert not saved.report.matching_jobs
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        rows = connection.execute(
            "SELECT payload_json, result_json FROM batch_candidates ORDER BY ordinal"
        ).fetchall()
        assert [json.loads(row[0])["normalized_job"]["description"] for row in rows] == [
            known.description,
            new.description,
        ]
        assert all(row[1] is None for row in rows)

    resumed_client = StubLLMClient([decision(True)])
    completed = run(tmp_path, resumed_client, command="evaluate", adapter=NoWebsiteAdapter({}))
    assert completed.pending_count == 0
    assert len(completed.report.matching_jobs) == 2
    assert len(resumed_client.requests) == 1  # Known judgment is reused only during evaluation.
    assert resumed_client.requests[0].user_prompt.find(new.description) >= 0


@pytest.mark.parametrize("partial", [False, True])
def test_discovery_only_returns_coverage_status_with_empty_or_partial_batch(tmp_path, partial):
    adapter = StubAdapter({}, failed={"failed"} if partial else set())
    client = StubLLMClient([])
    saved = daily.run_daily_scan(
        registry(source("healthy"), source("failed")),
        AdapterRegistry([adapter]),
        PROFILE,
        evaluator(client),
        database_path=tmp_path / "jobs.sqlite3",
        lock_path=tmp_path / "scan.lock",
        discovery_only=True,
        source_retry_count=0,
        scan_at=SCAN_AT,
        clock=lambda: SCAN_AT,
    )
    assert saved.exit_code == (2 if partial else 0)
    assert saved.pending_count == 0
    assert not client.requests
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM daily_batch").fetchone()[0] == 1


def test_resume_keeps_completed_results_and_completed_resume_makes_no_calls(tmp_path):
    first_client = StubLLMClient([decision(True)])
    model = evaluator(first_client)
    model._budget = UsageBudget(UsageLimits(1, 10000, 1000, 200))
    listings = tuple(
        job("healthy", str(i), "ML Engineer", DESCRIPTION + f" Listing {i}.") for i in range(2)
    )
    first = run(tmp_path, first_client, listings=listings, model=model)
    assert first.pending_count == 1
    assert first.exit_code == 6
    assert len(first.report.matching_jobs) == 1
    resumed_client = StubLLMClient([decision(True)])
    resumed = run(tmp_path, resumed_client, command="evaluate", adapter=NoWebsiteAdapter({}))
    assert resumed.pending_count == 0
    assert len(resumed.report.matching_jobs) == 2
    assert len(resumed_client.requests) == 1
    assert resumed.report.metrics.listing_count == 2
    assert resumed.report.usage.request_count == 2
    complete_client = StubLLMClient([])
    again = run(tmp_path, complete_client, command="evaluate", adapter=NoWebsiteAdapter({}))
    assert len(again.report.matching_jobs) == 2
    assert not complete_client.requests


def test_force_bypasses_cache_and_resume_finishes_its_own_attempt(tmp_path):
    run(
        tmp_path,
        StubLLMClient([decision(True), decision(True)]),
        listings=tuple(
            job("healthy", str(i), "ML Engineer", DESCRIPTION + f" Listing {i}.") for i in range(2)
        ),
    )
    forced_client = StubLLMClient([decision(False)])
    model = evaluator(forced_client)
    model._budget = UsageBudget(UsageLimits(1, 10000, 1000, 200))
    forced = run(tmp_path, forced_client, command="force_reevaluate", model=model)
    assert forced.pending_count == 1
    assert not forced.report.matching_jobs
    remaining = StubLLMClient([decision(False)])
    completed = run(tmp_path, remaining, command="evaluate")
    assert completed.pending_count == 0
    assert len(remaining.requests) == 1
    assert not completed.report.matching_jobs
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM llm_requests WHERE discarded_reason = 'force_reevaluate'"
            ).fetchone()[0]
            == 2
        )


def test_changed_title_cannot_reuse_same_description_cache(tmp_path):
    run(tmp_path, StubLLMClient([decision(True)]))
    changed = job("healthy", "1", "Senior ML Engineer", DESCRIPTION)
    client = StubLLMClient([decision(False)])
    result = run(tmp_path, client, listings=(changed,))
    assert len(client.requests) == 1
    assert not result.report.matching_jobs


def test_three_same_day_scans_count_one_sighting_and_keep_known_results(tmp_path):
    run(tmp_path, StubLLMClient([decision(True)]))
    for _ in range(2):
        client = StubLLMClient([])
        result = run(tmp_path, client)
        assert not client.requests
        assert len(result.report.matching_jobs) == 1
        assert result.report.matching_jobs[0].new_identity is False
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        assert connection.execute("SELECT sighting_count FROM jobs").fetchone()[0] == 1


def test_provider_outage_stops_at_first_job_and_all_pending_work_can_resume(tmp_path):
    client = FailingLLMClient()
    listings = tuple(job("healthy", str(i), "ML Engineer", DESCRIPTION) for i in range(3))
    result = run(tmp_path, client, listings=listings)
    assert len(client.requests) == 1
    assert result.pending_count == 3
    assert result.halt_reason == "llm_provider_failure"
    resumed = run(tmp_path, StubLLMClient([decision(True)] * 3), command="evaluate")
    assert len(resumed.report.matching_jobs) == 3


def test_staged_reply_survives_crash_before_result_commit(tmp_path, monkeypatch):
    original = daily._commit_result

    def crash(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(daily, "_commit_result", crash)
    client = StubLLMClient([decision(True)])
    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, client)
    monkeypatch.setattr(daily, "_commit_result", original)
    resume_client = StubLLMClient([])
    result = run(tmp_path, resume_client, command="evaluate")
    assert len(result.report.matching_jobs) == 1
    assert not resume_client.requests
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        row = connection.execute("SELECT state, response_json FROM llm_requests").fetchone()
        assert tuple(row) == ("consumed", None)


def test_result_and_progress_roll_back_together(tmp_path, monkeypatch):
    from job_finder.persistence.batches import BatchRepository

    original = BatchRepository.finish_candidate

    def crash(self, *args, **kwargs):
        raise RuntimeError("synthetic commit failure")

    monkeypatch.setattr(BatchRepository, "finish_candidate", crash)
    with pytest.raises(RuntimeError, match="synthetic"):
        run(tmp_path, StubLLMClient([decision(True)]))
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        assert connection.execute("SELECT evaluation_status FROM jobs").fetchone()[0] == "pending"
        assert connection.execute("SELECT result_json FROM batch_candidates").fetchone()[0] is None
    monkeypatch.setattr(BatchRepository, "finish_candidate", original)
    result = run(tmp_path, StubLLMClient([]), command="evaluate")
    assert len(result.report.matching_jobs) == 1


def test_fatal_discovery_discards_previous_batch_and_does_not_observe_new_jobs(
    tmp_path, monkeypatch
):
    run(tmp_path, StubLLMClient([decision(True)]))

    def crash(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(daily, "_ensure_description", crash)
    with pytest.raises(KeyboardInterrupt):
        run(
            tmp_path, StubLLMClient([]), listings=(job("healthy", "2", "ML Engineer", DESCRIPTION),)
        )
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM daily_batch").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert (
            connection.execute("SELECT discarded_reason FROM llm_requests").fetchone()[0]
            == "new_scan"
        )
    with pytest.raises(CheckpointError, match="fresh scan"):
        run(tmp_path, StubLLMClient([]), command="evaluate")


def test_still_listed_but_aged_out_job_is_not_absent(tmp_path):
    listing = job("healthy", "1", "ML Engineer", DESCRIPTION, uncertain_date=True)
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        repository = JobStateRepository(connection)
        record = repository.observe_listing(
            listing, observed_at=SCAN_AT - timedelta(days=20), profile_version=PROFILE.version
        ).record
        repository.record_lifecycle(record.job_key, JobLifecycleState(sighting_count=2))
    result = run(tmp_path, StubLLMClient([]), listings=(listing,))
    assert result.report.metrics.retained_candidate_count == 0
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        record = JobStateRepository(connection).require(job_identity(listing).job_key)
        assert record.consecutive_absences == 0
        assert record.sighting_count == 3
        assert record.last_seen_at == SCAN_AT


def test_three_same_day_absences_do_not_close_a_job(tmp_path):
    listing = job("healthy", "1", "ML Engineer", DESCRIPTION)
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        repository = JobStateRepository(connection)
        record = repository.observe_listing(
            listing, observed_at=SCAN_AT - timedelta(days=1), profile_version=PROFILE.version
        ).record
        repository.record_lifecycle(record.job_key, JobLifecycleState(sighting_count=2))
    for _ in range(3):
        run(tmp_path, StubLLMClient([]), listings=(), expiry_dry_run=False)
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        record = JobStateRepository(connection).require(job_identity(listing).job_key)
        assert record.consecutive_absences == 1
        assert record.status == "active"


def test_prompt_content_change_requires_force_even_without_version_bump(tmp_path):
    run(tmp_path, StubLLMClient([decision(True)]))
    model = evaluator(StubLLMClient([decision(False)]))
    model._prompt = replace(
        model._prompt, system_prompt=model._prompt.system_prompt + "\nMore specific rules."
    )
    with pytest.raises(CheckpointError, match="rules changed"):
        run(tmp_path, model.client, command="evaluate", model=model)
    result = run(tmp_path, model.client, command="force_reevaluate", model=model)
    assert not result.report.matching_jobs


def test_backup_restore_contains_batch_progress_and_response_journal(tmp_path):
    run(tmp_path, StubLLMClient([decision(True)]))
    backup_state(tmp_path / "jobs.sqlite3", tmp_path / "backup.sqlite3")
    restore_state(tmp_path / "backup.sqlite3", tmp_path / "restored.sqlite3")
    with migrated_database(tmp_path / "restored.sqlite3") as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM batch_candidates WHERE result_json IS NOT NULL"
            ).fetchone()[0]
            == 1
        )
        assert connection.execute("SELECT COUNT(*) FROM llm_requests").fetchone()[0] == 1


def test_report_failure_preserves_completed_batch_for_regeneration(tmp_path):
    def fail(result):
        raise OSError("synthetic report failure")

    with pytest.raises(OSError, match="report failure"):
        run(tmp_path, StubLLMClient([decision(True)]), on_result=fail)
    result = run(tmp_path, StubLLMClient([]), command="evaluate")
    assert len(result.report.matching_jobs) == 1


def test_cached_merged_not_ai_judgment_remains_a_rejection(tmp_path):
    listing = replace(_job("1", "ML Engineer"), company_id="healthy")

    def model(client):
        return MergedEvaluator(
            client=client,
            prompt=load_merged_prompt(Path("config/merged_prompt.toml")),
            model_policy=ModelPolicy("test", "stub", "1"),
            budget=UsageBudget(UsageLimits(20, 20000, 4000, 200)),
        )

    run(tmp_path, None, listings=(listing,), model=model(_Client([_merged_response("not_ai")])))
    client = _Client([])
    result = run(tmp_path, None, listings=(listing,), model=model(client))
    assert not client.requests
    assert not result.report.matching_jobs
    assert result.report.metrics.conditional_rejection_count == 1


def _merged_without_seniority_quote() -> str:
    """Valid under the merged contract, invalid under the standalone seniority one."""
    response = json.loads(_merged_response("core_ai"))
    response.update(
        seniority_match="uncertain",
        seniority_evidence="",  # the merged prompt asks for "" rather than an invented quote
        seniority_reason="No stated experience requirement. " * 40,  # > standalone 1000 cap
    )
    return json.dumps(response)


class _HaltingClient(_Client):
    """Answers from ``contents``, then fails like a gateway timeout."""

    def complete(self, request, policy):
        if not self.contents:
            from job_finder.matching.evaluator import LLMProviderError

            raise LLMProviderError("gateway timed out")
        return super().complete(request, policy)


def _merged_model(client):
    return MergedEvaluator(
        client=client,
        prompt=load_merged_prompt(Path("config/merged_prompt.toml")),
        model_policy=ModelPolicy("test", "stub", "1"),
        budget=UsageBudget(UsageLimits(20, 20000, 4000, 2000)),
    )


def test_report_accepts_merged_decision_without_seniority_quote(tmp_path):
    # Observed live: 55 of 3,806 gpt-6-luna judgments had an empty seniority quote. The
    # report re-validated them with the standalone contract and crashed after evaluation.
    listing = replace(_job("1", "ML Engineer"), company_id="healthy")
    client = _Client([_merged_without_seniority_quote()])
    result = run(tmp_path, None, listings=(listing,), model=_merged_model(client))
    assert result.pending_count == 0
    assert result.exit_code == 0
    [review] = [
        item for item in result.report.review_candidates if item.category == "seniority_uncertain"
    ]
    assert review.evidence == ""
    assert review.reason.startswith("No stated experience requirement.")


def test_gateway_halt_after_quoteless_decision_stays_resumable(tmp_path):
    # Observed live: a timeout halted gpt-6.1-sol, then the halt report crashed on the
    # same row, so the run exited 3 (fatal) instead of 6 (resume with evaluate).
    # Distinct titles: identical requests would be answered from the judgment cache.
    listings = tuple(
        replace(_job(identifier, title), company_id="healthy")
        for identifier, title in (("1", "ML Engineer"), ("2", "Applied Scientist"))
    )
    client = _HaltingClient([_merged_without_seniority_quote()])
    result = run(tmp_path, None, listings=listings, model=_merged_model(client))
    assert result.halt_reason == "llm_provider_failure"
    assert result.pending_count == 1
    assert result.exit_code == 6


def test_midnight_does_not_stop_active_invocation_but_rejects_new_evaluation(tmp_path):
    from datetime import UTC, datetime

    times = iter(
        [datetime(2026, 9, 23, 18, 29, tzinfo=UTC)]
        + [datetime(2026, 9, 23, 18, 31, tzinfo=UTC)] * 10
    )
    result = daily.run_daily_scan(
        registry(source("healthy")),
        AdapterRegistry(
            [StubAdapter({"healthy": (job("healthy", "1", "ML Engineer", DESCRIPTION),)})]
        ),
        PROFILE,
        evaluator(StubLLMClient([decision(True)])),
        database_path=tmp_path / "jobs.sqlite3",
        lock_path=tmp_path / "scan.lock",
        clock=lambda: next(times),
        scan_at=SCAN_AT,
    )
    assert result.pending_count == 0
    assert result.admission_date == "2026-09-23"
    with pytest.raises(CheckpointError, match="midnight"):
        daily.run_daily_scan(
            registry(source("healthy")),
            AdapterRegistry([NoWebsiteAdapter({})]),
            PROFILE,
            evaluator(StubLLMClient([])),
            database_path=tmp_path / "jobs.sqlite3",
            lock_path=tmp_path / "scan.lock",
            command="evaluate",
            clock=lambda: datetime(2026, 9, 23, 18, 31, tzinfo=UTC),
        )


def test_interrupted_inflight_call_is_unknown_and_resume_can_send_again(tmp_path):
    class InterruptedClient:
        def complete(self, request, policy):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, InterruptedClient())
    result = run(tmp_path, StubLLMClient([decision(True)]), command="evaluate")
    assert result.pending_count == 0
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        rows = connection.execute(
            "SELECT state, input_tokens FROM llm_requests ORDER BY rowid"
        ).fetchall()
        assert tuple(rows[0]) == ("unknown", None)
        assert tuple(rows[1]) == ("consumed", 50)


def test_total_source_failure_discards_batch_without_paid_calls(tmp_path):
    run(tmp_path, StubLLMClient([decision(True)]))
    client = StubLLMClient([])
    with pytest.raises(RuntimeError, match="no enabled source completed"):
        run(tmp_path, client, adapter=StubAdapter({}, failed={"healthy"}))
    assert not client.requests
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM daily_batch").fetchone()[0] == 0


def test_partial_sources_preserve_coverage_and_resume_without_sites(tmp_path):
    sources = registry(source("healthy"), source("broken"))
    adapter = StubAdapter(
        {"healthy": (job("healthy", "1", "ML Engineer", DESCRIPTION),)}, failed={"broken"}
    )
    result = daily.run_daily_scan(
        sources,
        AdapterRegistry([adapter]),
        PROFILE,
        evaluator(StubLLMClient([decision(True)])),
        database_path=tmp_path / "jobs.sqlite3",
        lock_path=tmp_path / "scan.lock",
        clock=lambda: SCAN_AT,
        scan_at=SCAN_AT,
        source_retry_count=0,
    )
    assert result.exit_code == 2
    resumed = daily.run_daily_scan(
        sources,
        AdapterRegistry([NoWebsiteAdapter({})]),
        PROFILE,
        evaluator(StubLLMClient([])),
        database_path=tmp_path / "jobs.sqlite3",
        lock_path=tmp_path / "scan.lock",
        clock=lambda: SCAN_AT,
        command="evaluate",
    )
    assert resumed.report.metrics.failed_company_count == 1
    assert len(resumed.report.company_accounting) == 2
    assert resumed.report.source_failures == result.report.source_failures


def test_changed_discovery_rules_require_new_scan_even_for_force(tmp_path):
    run(tmp_path, StubLLMClient([decision(True)]))
    changed = replace(PROFILE, recency_window_days=9)
    with pytest.raises(CheckpointError, match="discovery filter"):
        run(tmp_path, StubLLMClient([]), command="force_reevaluate", profile=changed)


def test_previous_date_count_collapse_freezes_absence(tmp_path):
    listing = job("healthy", "1", "ML Engineer", DESCRIPTION)
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        repository = JobStateRepository(connection)
        record = repository.observe_listing(
            listing, observed_at=SCAN_AT - timedelta(days=1), profile_version=PROFILE.version
        ).record
        repository.record_lifecycle(record.job_key, JobLifecycleState(sighting_count=2))
        connection.execute(
            "INSERT INTO daily_company_counts VALUES ('healthy', ?, 100)",
            ((SCAN_AT - timedelta(days=1)).date().isoformat(),),
        )
    run(tmp_path, StubLLMClient([]), listings=())
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        assert connection.execute("SELECT consecutive_absences FROM jobs").fetchone()[0] == 0


def test_two_invalid_replies_are_terminal_review_and_keep_usage(tmp_path):
    result = run(tmp_path, StubLLMClient(["", ""]))
    assert result.pending_count == 0
    assert len(result.report.review_candidates) == 1
    assert result.report.usage.request_count == 2
    assert result.report.usage.measured_input_tokens == 100
    resumed = run(tmp_path, StubLLMClient([]), command="evaluate")
    assert len(resumed.report.review_candidates) == 1


def test_fresh_scan_freezes_description_even_for_previously_cached_job(tmp_path):
    from tests.test_scan import RetryingDetailAdapter

    listing = job("healthy", "1", "ML Engineer", DESCRIPTION)
    run(tmp_path, StubLLMClient([decision(True)]), listings=(listing,))
    no_text = replace(listing, description=None, description_hash=None)
    adapter = RetryingDetailAdapter(
        {"healthy": (no_text,)}, details={listing.external_job_id: listing}, failures_remaining=0
    )
    run(tmp_path, StubLLMClient([]), adapter=adapter)
    assert adapter.detail_requests == 1
    result = run(
        tmp_path,
        StubLLMClient([decision(False)]),
        command="force_reevaluate",
        adapter=NoWebsiteAdapter({}),
    )
    assert result.pending_count == 0
    assert not result.report.matching_jobs


def test_filled_posting_is_dropped_not_judged_and_keeps_its_job_row(tmp_path):
    # SAP still lists a filled requisition but its detail page says "position has been
    # filled". It must not reach the model or the report, and a known job's row must
    # survive (deleting it would make a live listing look new, see CLAUDE.md "Prune").
    from job_finder.adapters.errors import DetailPostingClosed
    from tests.test_scan import RetryingDetailAdapter

    class FilledAdapter(RetryingDetailAdapter):
        def get_job_detail(self, company_source, listing):
            self.detail_requests += 1
            raise DetailPostingClosed("position has been filled")

    full = replace(_job("1", "ML Engineer"), company_id="healthy")
    bare = replace(full, description=None, description_hash=None)
    adapter = FilledAdapter({"healthy": (bare,)})
    client = _Client([])

    result = run(tmp_path, None, adapter=adapter, model=_merged_model(client))

    assert adapter.detail_requests == 1
    assert client.requests == []
    assert result.pending_count == 0
    assert not result.report.review_candidates
    assert not result.report.matching_jobs
    assert result.report.metrics.description_failure_count == 0
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM batch_candidates").fetchone()[0] == 0

    # A job already known from an earlier scan keeps its row when it later turns up filled.
    run(tmp_path, StubLLMClient([decision(True)]), listings=(full,))
    run(tmp_path, None, adapter=FilledAdapter({"healthy": (bare,)}), model=_merged_model(client))
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM batch_candidates").fetchone()[0] == 0


def _title_only_reply(relevance: str, title: str) -> str:
    return json.dumps(
        {
            "work_summary": "Unknown beyond the title.",
            "relevance": relevance,
            "relevance_evidence": title,
            "relevance_reason": "Only the title is available.",
            "seniority_match": "uncertain",
            "detected_level": "mid",
            "required_experience": "unknown",
            "seniority_evidence": "",
            "seniority_reason": "No description states any requirement.",
        }
    )


def test_missing_description_is_judged_from_the_title(tmp_path):
    # Observed 2026-10-02: 79 candidates had no description (69 from one board with empty
    # job descriptions). All went straight to review although every title was non-AI work.
    from tests.test_scan import RetryingDetailAdapter

    listing = replace(
        _job("1", "ML Engineer"), company_id="healthy", description=None, description_hash=None
    )
    adapter = RetryingDetailAdapter({"healthy": (listing,)}, failures_remaining=99)
    client = _Client([_title_only_reply("not_ai", "ML Engineer")])

    result = run(tmp_path, None, adapter=adapter, model=_merged_model(client))

    assert result.pending_count == 0
    [request] = client.requests
    assert daily.NO_DESCRIPTION in request.user_prompt
    assert "ML Engineer" in request.user_prompt
    assert not result.report.review_candidates  # judged not_ai: hidden, not reviewed
    assert result.report.metrics.description_failure_count == 1
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        stored = json.loads(
            connection.execute("SELECT result_json FROM batch_candidates").fetchone()[0]
        )
    assert stored["description_error"]
    assert stored["judgment"]["relevance"] == "not_ai"


def test_title_only_verdict_is_redone_once_a_description_appears(tmp_path):
    from tests.test_scan import RetryingDetailAdapter

    full = replace(_job("1", "ML Engineer"), company_id="healthy")
    bare = replace(full, description=None, description_hash=None)
    run(
        tmp_path,
        None,
        adapter=RetryingDetailAdapter({"healthy": (bare,)}, failures_remaining=99),
        model=_merged_model(_Client([_title_only_reply("ai_involved", "ML Engineer")])),
    )
    client = _Client([_merged_response("core_ai")])

    run(
        tmp_path,
        None,
        adapter=RetryingDetailAdapter(
            {"healthy": (bare,)}, details={full.external_job_id: full}, failures_remaining=0
        ),
        model=_merged_model(client),
    )

    # The placeholder is part of the cached request, so a real description is a new
    # fingerprint: the title-only verdict is not reused.
    [request] = client.requests
    assert daily.NO_DESCRIPTION not in request.user_prompt


def _remote_listing():
    return replace(
        _job("1", "ML Engineer"),
        company_id="healthy",
        location_original="Remote - APAC",
        location_normalized=("remote - apac",),
    )


def _located_reply(relevance: str, fit: str, evidence: str, **overrides: object) -> str:
    reply = json.loads(_merged_response(relevance))
    reply.update(overrides)
    reply.update(
        location_fit=fit,
        location_evidence=evidence,
        location_reason="Judged from the stated location.",
    )
    return json.dumps(reply)


@pytest.mark.parametrize(
    ("relevance", "fit", "matches", "review_categories"),
    [
        ("core_ai", "india", 1, []),
        ("core_ai", "open_remote", 1, []),
        ("core_ai", "excluded", 0, []),
        ("core_ai", "uncertain", 0, ["location_uncertain"]),
        # Policy v1.2 section 6: shown, in its own category rather than among matches.
        ("core_ai", "relocation", 0, ["location_relocation"]),
        ("not_ai", "uncertain", 0, []),
    ],
)
def test_unresolved_location_is_judged_by_the_model(
    tmp_path, relevance, fit, matches, review_categories
):
    # to_change.md 2.4 (decided): the model decides India eligibility for locations the
    # filter cannot resolve. Those rows used to go straight to review, so the location
    # judgment never ran and irrelevant roles reached the queue unchecked.
    client = _Client([_located_reply(relevance, fit, "Remote - APAC")])

    result = run(tmp_path, None, listings=(_remote_listing(),), model=_merged_model(client))

    [request] = client.requests
    assert "Remote - APAC" in request.user_prompt
    assert "location_fit" in request.response_schema["properties"]
    assert result.pending_count == 0
    assert len(result.report.matching_jobs) == matches
    assert [item.category for item in result.report.review_candidates] == review_categories
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        stored = connection.execute(
            "SELECT verdict, location_fit, work_summary FROM jobs"
        ).fetchone()
    assert tuple(stored)[:2] == (relevance, fit)
    assert stored["work_summary"]


def test_replaying_invalid_reply_does_not_consume_new_invocation_budget(tmp_path):
    first_client = StubLLMClient([""])
    first_model = evaluator(first_client)
    first_model._budget = UsageBudget(UsageLimits(1, 10000, 1000, 200))
    first = run(tmp_path, first_client, model=first_model)
    assert first.pending_count == 1
    next_client = StubLLMClient([decision(True)])
    next_model = evaluator(next_client)
    next_model._budget = UsageBudget(UsageLimits(1, 10000, 1000, 200))
    resumed = run(tmp_path, next_client, command="evaluate", model=next_model)
    assert resumed.pending_count == 0
    assert len(next_client.requests) == 1
    assert resumed.report.usage.request_count == 2


def test_corrupt_database_batch_is_rejected_before_calls_or_outputs(tmp_path):
    run(tmp_path, StubLLMClient([decision(True)]))
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        connection.execute("UPDATE daily_batch SET metadata_json = '{}' ")
    with pytest.raises(CheckpointError, match="corrupt"):
        run(tmp_path, StubLLMClient([]), command="evaluate", adapter=NoWebsiteAdapter({}))


def test_valid_reply_without_usage_completes_without_paid_replay(tmp_path):
    from job_finder.matching.evaluator import LLMResponse

    class UnknownUsageClient:
        def complete(self, request, policy):
            return LLMResponse(decision(True), 0, 0, usage_known=False)

    result = run(tmp_path, UnknownUsageClient())
    assert result.pending_count == 0
    assert result.report.unknown_usage_request_count == 1
    assert result.report.usage.measured_input_tokens == 0
    resumed = run(tmp_path, StubLLMClient([]), command="evaluate")
    assert len(resumed.report.matching_jobs) == 1
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        assert connection.execute("SELECT input_tokens FROM llm_requests").fetchone()[0] is None


@pytest.mark.parametrize("fit", ["uncertain", "relocation"])
def test_a_closed_seniority_hides_a_location_review_row(tmp_path, fit):
    # Policy v1.2 section 1: "not eligible" hides a job whatever else is true. Before
    # schema 2 an uncertain location went to review even when seniority was already false.
    client = _Client([_located_reply("core_ai", fit, "Remote - APAC", seniority_match=False)])

    result = run(tmp_path, None, listings=(_remote_listing(),), model=_merged_model(client))

    assert not result.report.matching_jobs
    assert not result.report.review_candidates
