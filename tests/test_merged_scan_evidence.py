"""The merged call's evidence must survive the trip from model to database.

Until migration 5 only the three-way `verdict` enum was persisted, so the judgment that
rejects ~59% of evaluated jobs was the one judgment nobody could audit afterwards. These
tests run a real `process_filter_report` against a stub LLM and assert the quotes land in
SQLite -- the unit tests either side of this seam both passed while nothing was wired
between them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from job_finder.adapters.base import AdapterRegistry
from job_finder.collection import collect_listings
from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.core.search_profile import load_search_profile
from job_finder.core.source_contracts import (
    AdapterOutcome,
    AdapterResult,
    AdapterType,
    CompanySource,
)
from job_finder.matching.evaluator import (
    LLMRequest,
    LLMResponse,
    ModelPolicy,
    UsageBudget,
    UsageLimits,
)
from job_finder.matching.merged_evaluator import MergedEvaluator
from job_finder.matching.merged_prompt import load_merged_prompt
from job_finder.persistence.database import migrated_database
from job_finder.persistence.repository import JobRecord, JobStateRepository
from job_finder.reporting.scan_report import render_scan_markdown
from job_finder.scan import ScanReport, process_filter_report
from tests.test_scan import registry, source

ROOT = Path(__file__).resolve().parents[1]
SCAN_AT = datetime(2026, 9, 23, 5, 0, tzinfo=UTC)
PROFILE = load_search_profile(ROOT / "config" / "search_profile.toml")

DESCRIPTION = (
    "You will train and deploy production machine learning models for our ranking stack. "
    "We are looking for 3+ years of experience building ML systems at scale."
)


def _job(identifier: str, title: str) -> NormalizedJob:
    return NormalizedJob(
        1,
        "example-co",
        "ashby",
        identifier,
        title,
        title.casefold(),
        "Bengaluru, India",
        ("bengaluru india",),
        SCAN_AT - timedelta(days=1),
        (SCAN_AT - timedelta(days=1)).isoformat(),
        DateBasis.PUBLISHED,
        f"https://jobs.example.com/example-co/{identifier}",
        DESCRIPTION,
        hashlib.sha256(DESCRIPTION.encode("utf-8")).hexdigest(),
    )


@dataclass
class _Adapter:
    jobs: tuple[NormalizedJob, ...]
    adapter_type: AdapterType = AdapterType.ASHBY

    def list_jobs(self, company_source: CompanySource) -> AdapterResult:
        return AdapterResult(1, company_source, AdapterOutcome.SUCCESS, self.jobs, 1, True, ())


@dataclass
class _Client:
    contents: list[str]
    requests: list[LLMRequest] = field(default_factory=list)

    def complete(self, request: LLMRequest, policy: ModelPolicy) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(self.contents.pop(0), input_tokens=50, output_tokens=20)


def _merged_response(relevance: str) -> str:
    """A valid merged response. Every quote must be verbatim or the parser rejects it."""
    return json.dumps(
        {
            "work_summary": "Trains and deploys production machine learning models.",
            "relevance": relevance,
            "relevance_evidence": "train and deploy production machine learning models",
            "relevance_reason": "Core ML engineering, not an adjacent analytics role.",
            "seniority_match": True,
            "detected_level": "mid",
            "required_experience": "3+ years",
            "seniority_evidence": "3+ years of experience building ML systems",
            "seniority_reason": "Matches the target band.",
        }
    )


def _run_report(tmp_path: Path, contents: list[str]) -> ScanReport:
    adapter = _Adapter((_job("REQ-1", "Machine Learning Engineer"),))
    test_registry = registry(source("example-co"))
    filter_report = collect_listings(
        test_registry,
        AdapterRegistry([adapter]),
        PROFILE,
        scan_at=SCAN_AT,
        source_retry_count=0,
    )
    evaluator = MergedEvaluator(
        client=_Client(contents),
        prompt=load_merged_prompt(ROOT / "config" / "merged_prompt.toml"),
        model_policy=ModelPolicy("test", "stub", "1"),
        budget=UsageBudget(UsageLimits(20, 20_000, 4_000, 200)),
    )
    with migrated_database(tmp_path / "report.sqlite3") as connection:
        return process_filter_report(
            filter_report,
            test_registry,
            AdapterRegistry([adapter]),
            PROFILE,
            evaluator,
            JobStateRepository(connection),
            run_id="scan-test",
            started_at=SCAN_AT,
            completed_at=SCAN_AT + timedelta(minutes=1),
        )


def _run(tmp_path: Path, contents: list[str]) -> list[JobRecord]:
    adapter = _Adapter((_job("REQ-1", "Machine Learning Engineer"),))
    test_registry = registry(source("example-co"))
    filter_report = collect_listings(
        test_registry,
        AdapterRegistry([adapter]),
        PROFILE,
        scan_at=SCAN_AT,
        source_retry_count=0,
    )
    evaluator = MergedEvaluator(
        client=_Client(contents),
        prompt=load_merged_prompt(ROOT / "config" / "merged_prompt.toml"),
        model_policy=ModelPolicy("test", "stub", "1"),
        budget=UsageBudget(UsageLimits(20, 20_000, 4_000, 200)),
    )
    with migrated_database(tmp_path / "jobs.sqlite3") as connection:
        repository = JobStateRepository(connection)
        process_filter_report(
            filter_report,
            test_registry,
            AdapterRegistry([adapter]),
            PROFILE,
            evaluator,
            repository,
            run_id="scan-test",
            started_at=SCAN_AT,
            completed_at=SCAN_AT + timedelta(minutes=1),
        )
        keys = [str(row["job_key"]) for row in connection.execute("SELECT job_key FROM jobs")]
        return [repository.require(key) for key in keys]


def test_relevance_evidence_reaches_the_database(tmp_path: Path) -> None:
    stored = _run(tmp_path, [_merged_response("core_ai")])

    assert len(stored) == 1
    record = stored[0]
    assert record.verdict == "core_ai"
    assert record.relevance_evidence == "train and deploy production machine learning models"
    assert record.relevance_reason == "Core ML engineering, not an adjacent analytics role."


def test_a_rejected_job_still_records_why_it_was_rejected(tmp_path: Path) -> None:
    """The rejection path `continue`s immediately, so it is the easiest one to miss.

    It is also the one that matters most: 153 of 259 evaluated jobs in the 2026-09-30 scan
    were dropped as unrelated (now not_ai), and none of them could be explained after the fact.
    """
    stored = _run(tmp_path, [_merged_response("not_ai")])

    assert len(stored) == 1
    record = stored[0]
    assert record.verdict == "not_ai"
    assert record.relevance_reason == "Core ML engineering, not an adjacent analytics role."


def test_location_evidence_is_absent_when_the_filter_resolved_it(tmp_path: Path) -> None:
    """Bengaluru resolves deterministically, so the model is never asked about location."""
    stored = _run(tmp_path, [_merged_response("core_ai")])

    record = stored[0]
    assert record.location_evidence is None
    assert record.location_reason is None


def test_the_description_is_stored_alongside_its_hash(tmp_path: Path) -> None:
    stored = _run(tmp_path, [_merged_response("core_ai")])

    record = stored[0]
    assert record.description == DESCRIPTION
    assert record.description_hash == hashlib.sha256(DESCRIPTION.encode("utf-8")).hexdigest()


def test_the_report_carries_the_relevance_verdict_on_the_run_that_produced_it(
    tmp_path: Path,
) -> None:
    """Regression: the record reaching the report was fetched before record_verdict ran.

    Every row would have reported a blank verdict on the very run that judged it, and only
    picked one up on a later cached run -- the worst possible failure mode, because it
    looks correct as soon as you re-run to check.
    """
    report = _run_report(tmp_path, [_merged_response("core_ai")])

    assert len(report.matching_jobs) == 1
    match = report.matching_jobs[0]
    assert match.relevance == "core_ai"
    assert match.relevance_reason == "Core ML engineering, not an adjacent analytics role."


def test_an_ai_involved_match_is_distinguishable_in_the_rendered_report(
    tmp_path: Path,
) -> None:
    """2.6 tiers ai_involved below core_ai; before this it rendered identically."""
    report = _run_report(tmp_path, [_merged_response("ai_involved")])
    markdown = render_scan_markdown(report)

    assert report.matching_jobs[0].relevance == "ai_involved"
    assert "| Relevance |" in markdown
    assert "ai_involved" in markdown
