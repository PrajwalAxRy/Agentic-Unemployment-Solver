"""Command-line entry point for the job finder."""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import shlex
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from job_finder import __version__
from job_finder.accounting import export_accounting, read_accounting, usage_statistics
from job_finder.adapters.aganitha_careers import AganithaCareersAdapter
from job_finder.adapters.airbnb_careers import AirbnbCareersAdapter
from job_finder.adapters.amazon_jobs import AmazonJobsAdapter
from job_finder.adapters.apple_jobs import AppleJobsAdapter
from job_finder.adapters.ashby import AshbyAdapter
from job_finder.adapters.atlassian_careers import AtlassianCareersAdapter
from job_finder.adapters.atomicwork import AtomicworkWebflowAdapter
from job_finder.adapters.base import AdapterRegistry
from job_finder.adapters.booking_careers import BookingCareersAdapter
from job_finder.adapters.connectivity import ConnectivityPolicy, ConnectivityWaiter
from job_finder.adapters.custom import CustomAdapterRouter
from job_finder.adapters.darwinbox import DarwinboxAdapter
from job_finder.adapters.deshaw_india import DeshawIndiaAdapter
from job_finder.adapters.eightfold import EightfoldAdapter
from job_finder.adapters.freshteam import FreshteamAdapter
from job_finder.adapters.galaxeye_zoho import GalaxEyeZohoAdapter
from job_finder.adapters.gnani_careers import GnaniCareersAdapter
from job_finder.adapters.google_careers import GoogleCareersAdapter
from job_finder.adapters.greenhouse import GreenhouseAdapter
from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy
from job_finder.adapters.index_exchange import IndexExchangeCareersAdapter
from job_finder.adapters.intuit_careers import IntuitCareersAdapter
from job_finder.adapters.jobvite import JobviteAdapter
from job_finder.adapters.lever import LeverAdapter
from job_finder.adapters.microsoft_careers import MicrosoftCareersAdapter
from job_finder.adapters.navi_careers import NaviCareersAdapter
from job_finder.adapters.oracle_cloud import OracleCloudAdapter
from job_finder.adapters.pageup_xml_feed import PageUpXmlFeedAdapter
from job_finder.adapters.pcsx_careers import PcsxCareersAdapter
from job_finder.adapters.quadeye_careers import QuadeyeCareersAdapter
from job_finder.adapters.qure_careers import QureCareersAdapter
from job_finder.adapters.recruiterflow import RecruiterflowAdapter
from job_finder.adapters.rippling import RipplingAdapter
from job_finder.adapters.sensehq import SenseHqAdapter
from job_finder.adapters.smartrecruiters import SmartRecruitersAdapter
from job_finder.adapters.stripe_careers import StripeCareersAdapter
from job_finder.adapters.successfactors import SuccessFactorsAdapter
from job_finder.adapters.swiggy_careers import SwiggyCareersAdapter
from job_finder.adapters.twilio_careers import TwilioCareersAdapter
from job_finder.adapters.workday import WorkdayAdapter
from job_finder.checkpoint import CheckpointError
from job_finder.collection import (
    collect_listings,
    write_filter_report,
    write_filter_review,
)
from job_finder.core.company_registry import load_company_registry
from job_finder.core.job_probe import probe_job_url
from job_finder.core.search_profile import load_search_profile
from job_finder.core.source_contracts import AdapterType
from job_finder.cost import (
    DEFAULT_LEDGER_PATH,
    daily_totals,
    format_bytes,
    summarise,
)
from job_finder.daily_scan import DailyScanResult, run_daily_scan
from job_finder.logging_setup import configure_logging, progress_logger
from job_finder.matching.evaluation_set import load_seniority_evaluation_set
from job_finder.matching.evaluator import SeniorityEvaluator, UsageBudget
from job_finder.matching.merged_evaluator import MergedEvaluator
from job_finder.matching.merged_prompt import load_merged_prompt
from job_finder.matching.openai_client import (
    AmdGatewayClient,
    GatewayProviderError,
    check_gateway_connectivity,
    configuration_presence,
    load_gateway_settings,
)
from job_finder.matching.prompt import load_seniority_prompt
from job_finder.matching.service import JobEvaluator
from job_finder.persistence.batches import india_date
from job_finder.persistence.database import CURRENT_SCHEMA_VERSION
from job_finder.persistence.locking import ScanAlreadyRunningError
from job_finder.persistence.maintenance import (
    backup_state,
    inspect_state,
    prune_descriptions,
    reset_state,
    restore_state,
)
from job_finder.repair import (
    build_repair_request,
    load_and_validate_repair_proposal,
    load_repair_request,
    preview_registry_with_proposal,
    write_repair_artifact,
)
from job_finder.reporting.scan_report import write_scan_markdown
from job_finder.scan import (
    SCAN_REPORT_SCHEMA_VERSION,
    write_scan_report,
)
from job_finder.terminal import ScanDisplay, parse_progress
from job_finder.verification import (
    load_verification_baseline,
    verify_adapter_sources,
    verify_enabled_sources,
    write_verification_report,
)

_LOGGER = logging.getLogger(__name__)

_PHASE_GATE_UNAVAILABLE = (
    "The '{command}' command is a phase-gate tool that lives in scripts/phase_gates/ and "
    "is not part of the installed package. Run it from a source checkout of the "
    "repository."
)


def _load_phase_gate(module_suffix: str, command: str) -> Any:
    """Import a relocated phase-gate module on demand.

    These modules were moved out of the package (``to_change.md`` 6.7 / decision B) because
    a ~100-minute idempotency test and a one-time report generator are not wheel material.
    They are imported lazily so that an installed ``job-finder`` still starts cleanly --
    only the three phase-gate subcommands are unavailable there, and they say so.
    """
    try:
        module = importlib.import_module(f"scripts.phase_gates.{module_suffix}")
    except ModuleNotFoundError as error:  # pragma: no cover - depends on install layout
        raise SystemExit(_PHASE_GATE_UNAVAILABLE.format(command=command)) from error
    return module


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level command-line parser."""
    parser = argparse.ArgumentParser(prog="job-finder")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Log per-job detail to the log file and mirror progress to stderr.",
    )
    parser.add_argument(
        "--log-directory",
        type=Path,
        default=Path("state"),
        help="State directory containing logs/ (default: state).",
    )
    subparsers = parser.add_subparsers(dest="command")
    verify = subparsers.add_parser(
        "verify-sources",
        help="Run read-only listing verification without modifying job history.",
    )
    selection = verify.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--adapter",
        choices=(
            AdapterType.ASHBY.value,
            AdapterType.CUSTOM.value,
            AdapterType.DARWINBOX.value,
            AdapterType.EIGHTFOLD.value,
            AdapterType.FRESHTEAM.value,
            AdapterType.GREENHOUSE.value,
            AdapterType.JOBVITE.value,
            AdapterType.LEVER.value,
            AdapterType.ORACLE_CLOUD.value,
            AdapterType.RECRUITERFLOW.value,
            AdapterType.RIPPLING.value,
            AdapterType.SENSEHQ.value,
            AdapterType.SMARTRECRUITERS.value,
            AdapterType.SUCCESSFACTORS.value,
            AdapterType.WORKDAY.value,
        ),
    )
    selection.add_argument(
        "--all-enabled",
        action="store_true",
        help="Verify every enabled source in canonical registry order.",
    )
    verify.add_argument("--company-id", action="append", default=[])
    verify.add_argument("--registry", type=Path, default=Path("config/company_sources.json"))
    verify.add_argument(
        "--output",
        type=Path,
        default=Path("reports/source_verification.json"),
    )
    verify.add_argument("--timeout", type=float, default=15.0)
    verify.add_argument(
        "--source-retries",
        type=int,
        default=2,
        help="Retry an incomplete full-source scan this many times (default: 2).",
    )
    verify.add_argument(
        "--baseline",
        type=Path,
        help="Prior sanitized verification JSON used to detect result-count collapse.",
    )
    measure = subparsers.add_parser(
        "measure-recency",
        help="Normalize all enabled listings and measure ten-day date coverage.",
    )
    measure.add_argument("--registry", type=Path, default=Path("config/company_sources.json"))
    measure.add_argument("--profile", type=Path, default=Path("config/search_profile.toml"))
    measure.add_argument(
        "--output",
        type=Path,
        default=Path("reports/recency_measurement.json"),
    )
    measure.add_argument("--timeout", type=float, default=15.0)
    measure.add_argument(
        "--source-retries",
        type=int,
        default=2,
        help="Retry an incomplete full-source scan this many times (default: 2).",
    )
    filter_jobs = subparsers.add_parser(
        "filter-jobs",
        help="Run complete-registry recency, role, and India-location filtering.",
    )
    filter_jobs.add_argument("--registry", type=Path, default=Path("config/company_sources.json"))
    filter_jobs.add_argument("--profile", type=Path, default=Path("config/search_profile.toml"))
    filter_jobs.add_argument(
        "--output",
        type=Path,
        default=Path("reports/phase6_filter_verification.json"),
    )
    filter_jobs.add_argument(
        "--review-output",
        type=Path,
        default=Path("docs/reviews/h6_filter_review.md"),
    )
    filter_jobs.add_argument("--timeout", type=float, default=15.0)
    filter_jobs.add_argument("--source-retries", type=int, default=2)
    costs = subparsers.add_parser(
        "costs",
        help="Show what past runs cost, per day and in total.",
    )
    costs.add_argument("--database", type=Path, default=Path("state/jobs.sqlite3"))
    costs.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
    costs.add_argument(
        "--days",
        type=int,
        default=30,
        help="How many of the most recent days to list. 0 shows every day on record.",
    )

    state = subparsers.add_parser(
        "state",
        help="Inspect or maintain the local job-history database.",
    )
    state_subparsers = state.add_subparsers(dest="state_command", required=True)
    state_inspect = state_subparsers.add_parser("inspect", help="Show schema and record counts.")
    state_inspect.add_argument("--database", type=Path, default=Path("state/jobs.sqlite3"))
    state_backup = state_subparsers.add_parser("backup", help="Create a new verified backup.")
    state_backup.add_argument("--database", type=Path, default=Path("state/jobs.sqlite3"))
    state_backup.add_argument("--output", type=Path, required=True)
    state_restore = state_subparsers.add_parser(
        "restore",
        help="Restore a backup to a new path without overwriting existing state.",
    )
    state_restore.add_argument("--backup", type=Path, required=True)
    state_restore.add_argument("--output", type=Path, required=True)
    state_reset = state_subparsers.add_parser(
        "reset",
        help="Back up and clear existing state after exact path confirmation.",
    )
    state_reset.add_argument("--database", type=Path, default=Path("state/jobs.sqlite3"))
    state_reset.add_argument("--backup", type=Path, required=True)
    state_reset.add_argument("--confirm-database", required=True)
    state_reset.add_argument("--lock", type=Path, default=Path("state/scan.lock"))
    state_prune = state_subparsers.add_parser(
        "prune",
        help="Clear stored description text for jobs not seen recently. Keeps the rows.",
    )
    state_prune.add_argument("--database", type=Path, default=Path("state/jobs.sqlite3"))
    state_prune.add_argument("--backup", type=Path, required=True)
    state_prune.add_argument("--confirm-database", required=True)
    state_prune.add_argument("--lock", type=Path, default=Path("state/scan.lock"))
    state_prune.add_argument(
        "--older-than-days",
        type=int,
        default=90,
        help=(
            "Clear descriptions for jobs whose last sighting is older than this "
            "(default: 90). Measured on last_seen_at, so a long-running job that is still "
            "live every week is never touched."
        ),
    )
    persistence = subparsers.add_parser(
        "verify-persistence",
        help="Run two full filtered passes against disposable state and verify idempotency.",
    )
    persistence.add_argument("--registry", type=Path, default=Path("config/company_sources.json"))
    persistence.add_argument("--profile", type=Path, default=Path("config/search_profile.toml"))
    persistence.add_argument(
        "--database",
        type=Path,
        default=Path("state/phase7_validation.sqlite3"),
    )
    persistence.add_argument(
        "--lock",
        type=Path,
        default=Path("state/phase7_validation.lock"),
    )
    persistence.add_argument(
        "--output",
        type=Path,
        default=Path("reports/phase7_persistence_verification.json"),
    )
    persistence.add_argument("--timeout", type=float, default=15.0)
    persistence.add_argument("--source-retries", type=int, default=2)
    persistence.add_argument("--passes", type=int, choices=(1, 2), default=2)
    persistence.add_argument(
        "--allow-existing",
        action="store_true",
        help="Continue a disposable validation database instead of requiring it to be empty.",
    )
    llm = subparsers.add_parser(
        "check-llm",
        help="Check redacted LLM configuration and optionally verify model access.",
    )
    llm.add_argument("--dotenv", type=Path, default=Path(".env"))
    llm.add_argument(
        "--presence-only",
        action="store_true",
        help="Report configured and missing variable names without making a network request.",
    )
    validate_seniority = subparsers.add_parser(
        "validate-seniority",
        help="Run the reviewed seniority set and a bounded unseen public-job batch.",
    )
    validate_seniority.add_argument(
        "--registry", type=Path, default=Path("config/company_sources.json")
    )
    validate_seniority.add_argument(
        "--profile", type=Path, default=Path("config/search_profile.toml")
    )
    validate_seniority.add_argument(
        "--evaluation-set",
        type=Path,
        default=Path("config/seniority_evaluation_set.json"),
    )
    validate_seniority.add_argument(
        "--prompt", type=Path, default=Path("config/seniority_prompt.toml")
    )
    validate_seniority.add_argument("--dotenv", type=Path, default=Path(".env"))
    validate_seniority.add_argument(
        "--output",
        type=Path,
        default=Path("reports/phase8_seniority_validation.json"),
    )
    validate_seniority.add_argument(
        "--review-output",
        type=Path,
        default=Path("docs/reviews/h9_seniority_quality_review.md"),
    )
    validate_seniority.add_argument("--live-limit", type=int, default=8)
    validate_seniority.add_argument(
        "--reuse-live-from",
        type=Path,
        help="Refresh the exact live sample from a prior generated Phase 8 report.",
    )
    validate_seniority.add_argument("--timeout", type=float, default=15.0)
    validate_seniority.add_argument("--source-retries", type=int, default=2)
    scan = subparsers.add_parser(
        "scan",
        help="Run the complete job-discovery pipeline once and write local reports.",
    )
    scan.add_argument("--registry", type=Path, default=Path("config/company_sources.json"))
    scan.add_argument("--profile", type=Path, default=Path("config/search_profile.toml"))
    scan.add_argument("--prompt", type=Path, default=Path("config/seniority_prompt.toml"))
    scan.add_argument(
        "--merged-prompt",
        type=Path,
        default=Path("config/merged_prompt.toml"),
        help="Merged relevance + seniority + location prompt (to_change.md 2.5).",
    )
    scan.add_argument(
        "--seniority-only",
        action="store_true",
        help=(
            "Fall back to the single-purpose seniority prompt. Disables the AI/ML "
            "relevance gate, so non-AI engineering roles will reach the report."
        ),
    )
    scan.add_argument(
        "--min-request-interval",
        type=float,
        default=0.0,
        help="Minimum seconds between requests to the same host (5.2/9.7).",
    )
    scan.add_argument(
        "--max-concurrent-per-host",
        type=int,
        default=0,
        help="Maximum concurrent requests per host. 0 disables the cap.",
    )
    scan.add_argument(
        "--enable-expiry",
        action="store_true",
        help=(
            "Actually close stale jobs. Off by default: 5.1 requires about a week of "
            "report-only observation first, and the dry-run report says which of its four "
            "checks are still unmet."
        ),
    )
    scan.add_argument(
        "--plain",
        action="store_true",
        help="Disable the live progress bar and colour; print plain log lines only.",
    )
    scan.add_argument(
        "--network-wait-minutes",
        type=float,
        default=120.0,
        help=(
            "How long to wait for the network to return if it drops mid-scan, polling "
            "every 2 minutes. 0 disables waiting and fails companies immediately."
        ),
    )
    scan.add_argument(
        "--no-probe",
        action="store_true",
        help=(
            "Skip per-job liveness probing. Unsafe with expiry enabled -- at a 3-absence "
            "threshold the probe is the only guard against a truncated listing closing "
            "live jobs (10.F)."
        ),
    )
    scan.add_argument(
        "--discovery-only",
        action="store_true",
        help="Collect/filter listings and save full descriptions, then stop before evaluation. "
        "Use evaluate before midnight IST; only valid with a fresh scan.",
    )
    scan.add_argument(
        "--resume",
        action="store_true",
        help=("Alias for evaluate: resume the current database batch before midnight IST."),
    )
    scan.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="Retired file checkpoint option; explicit use is rejected. "
        "Checkpoints live in SQLite.",
    )
    scan.add_argument(
        "--cost-ledger",
        type=Path,
        default=DEFAULT_LEDGER_PATH,
        help="Append-only JSON Lines record of what each run cost.",
    )
    scan.add_argument("--dotenv", type=Path, default=Path(".env"))
    scan.add_argument("--database", type=Path, default=Path("state/jobs.sqlite3"))
    scan.add_argument("--lock", type=Path, default=Path("state/scan.lock"))
    scan.add_argument(
        "--json-output",
        type=Path,
        default=Path("reports/latest_scan.json"),
    )
    scan.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("reports/latest_scan.md"),
    )
    scan.add_argument("--timeout", type=float, default=15.0)
    scan.add_argument("--source-retries", type=int, default=2)
    for name, help_text in (
        ("evaluate", "Resume the current same-day database evaluation attempt."),
        ("force_reevaluate", "Evaluate the entire saved same-day batch again, bypassing cache."),
    ):
        subparsers.add_parser(name, parents=[scan], add_help=False, help=help_text)
    repair = subparsers.add_parser(
        "repair",
        help="Build or validate inactive source-repair artifacts without applying changes.",
    )
    repair_subparsers = repair.add_subparsers(dest="repair_command", required=True)
    repair_request = repair_subparsers.add_parser(
        "build-request",
        help="Build a sanitized evidence request for one unhealthy source.",
    )
    repair_request.add_argument(
        "--registry", type=Path, default=Path("config/company_sources.json")
    )
    repair_request.add_argument("--verification", type=Path, required=True)
    repair_request.add_argument("--company-id", required=True)
    repair_request.add_argument("--output", type=Path, required=True)
    repair_validate = repair_subparsers.add_parser(
        "validate-proposal",
        help="Validate an LLM repair proposal and preserve it as inactive.",
    )
    repair_validate.add_argument("--request", type=Path, required=True)
    repair_validate.add_argument("--proposal", type=Path, required=True)
    repair_validate.add_argument("--output", type=Path, required=True)
    repair_test = repair_subparsers.add_parser(
        "test-proposal",
        help="Verify an inactive configuration proposal in memory without editing the registry.",
    )
    repair_test.add_argument("--registry", type=Path, default=Path("config/company_sources.json"))
    repair_test.add_argument("--request", type=Path, required=True)
    repair_test.add_argument("--proposal", type=Path, required=True)
    repair_test.add_argument("--output", type=Path, required=True)
    repair_test.add_argument("--timeout", type=float, default=15.0)
    repair_test.add_argument("--source-retries", type=int, default=2)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""
    args = build_parser().parse_args(argv)
    # Daily logging starts only after admission under ScanLock. Other commands have
    # their own sink and cannot reset or append to the current daily scan log.
    if args.command not in {"scan", "evaluate", "force_reevaluate"}:
        log_path = configure_logging(
            state_directory=args.log_directory,
            verbose=args.verbose,
            filename="commands.log",
        )
        _LOGGER.info("cli_start command=%s version=%s log=%s", args.command, __version__, log_path)
    if args.command == "verify-sources":
        return _verify_sources(args)
    if args.command == "measure-recency":
        return _measure_recency(args)
    if args.command == "filter-jobs":
        return _filter_jobs(args)
    if args.command == "state":
        try:
            return _maintain_state(args)
        except ScanAlreadyRunningError as error:
            print(f"state=skipped reason=already_running error={error}")
            return 4
    if args.command == "verify-persistence":
        return _verify_persistence(args)
    if args.command == "check-llm":
        return _check_llm(args)
    if args.command == "validate-seniority":
        return _validate_seniority(args)
    if args.command in {"scan", "evaluate", "force_reevaluate"}:
        return _scan(args)
    if args.command == "repair":
        return _repair(args)
    if args.command == "costs":
        return _costs(args)
    return 0


def _costs(args: argparse.Namespace) -> int:
    """Read authoritative request spending, preserving unknown and discarded amounts."""
    history = read_accounting(args.database, args.ledger)
    if not history:
        print(f"costs=none ledger={args.ledger} database={args.database}")
        return 0
    rows = daily_totals(history)
    days = sorted({str(row["day"]) for row in rows})
    selected = set(days if args.days <= 0 else days[-args.days :])
    print(f"{'day (IST)':<12}{'currency':<10}{'requests':>10}{'known cost':>14}{'discarded':>14}")
    for row in rows:
        if str(row["day"]) not in selected:
            continue
        amount = (
            "unavailable"
            if row["unknown_requests"] == row["requests"]
            else f"{float(str(row['cost'])):.4f}"
        )
        print(
            f"{str(row['day']):<12}{str(row['currency']):<10}{str(row['requests']):>10}"
            f"{amount:>14}{float(str(row['discarded_cost'])):>14.4f}"
        )
        if row["unknown_requests"]:
            print(
                f"  {row['unknown_requests']} request(s) have unknown usage or pricing; "
                "total is incomplete"
            )
    for currency in sorted({item.currency for item in history}):
        group = [item for item in history if item.currency == currency]
        totals = summarise(group)
        known = totals["total_cost"]
        unknown = sum(item.request_count for item in group if not item.priced)
        discarded = sum(item.total_cost or 0.0 for item in group if item.discarded_reason)
        flagged = sum(item.request_count for item in group if item.discarded_reason)
        amount = f"{float(str(known)):.4f}" if any(item.priced for item in group) else "unavailable"
        print(
            f"known_total={currency} {amount}; discarded={currency} {discarded:.4f} "
            f"({flagged} request(s)); "
            f"unknown={unknown} request(s)"
        )
    print(
        "Discarded spending remains included. "
        "Unknown charges may include an interrupted paid request."
    )
    for stats in usage_statistics(args.database):
        _print_usage_statistics(stats)
    return 0


def _print_usage_statistics(stats: dict[str, Any]) -> None:
    def tokens(name: str) -> str:
        value = stats[name]
        return "n/a" if value is None else f"{value:.0f}"

    print(
        f"\nusage model={stats['model_policy']} requests={stats['requests']} "
        f"jobs={stats['jobs']} unknown_usage={stats['unknown_usage_requests']}"
    )
    print(
        f"  mean per request: input={tokens('mean_input_tokens')} "
        f"(cached={tokens('mean_cached_input_tokens')}, "
        f"cache_write={tokens('mean_cache_write_tokens')}) "
        f"output={tokens('mean_output_tokens')} "
        f"(reasoning={tokens('mean_reasoning_tokens')})"
    )
    if stats["breakdown_requests"] < stats["requests"] - stats["unknown_usage_requests"]:
        print(
            f"  cache/reasoning breakdown recorded for {stats['breakdown_requests']} request(s) "
            "only; the rest are priced with all input at the full rate"
        )
    if stats["total_cost"] is None:
        print("  cost unavailable: some requests are unpriced or in mixed currencies")
    else:
        print(
            f"  cost={stats['currency']} {stats['total_cost']:.4f} "
            f"per_request={stats['cost_per_request']:.6f} per_job={stats['cost_per_job']:.6f}"
        )


def _verify_sources(args: argparse.Namespace) -> int:
    registry = load_company_registry(args.registry)
    policy = HttpPolicy(timeout_seconds=args.timeout)
    client = BoundedHttpClient(policy=policy)
    adapters = _runtime_adapters(client)
    baseline = load_verification_baseline(args.baseline) if args.baseline is not None else None
    if args.all_enabled:
        if args.company_id:
            raise ValueError("--company-id cannot be combined with --all-enabled")
        report = verify_enabled_sources(
            registry,
            adapters,
            baseline=baseline,
            source_retry_count=args.source_retries,
            progress=_print_progress,
        )
    else:
        report = verify_adapter_sources(
            registry,
            adapters,
            AdapterType(args.adapter),
            company_ids=args.company_id,
            baseline=baseline,
            source_retry_count=args.source_retries,
            progress=_print_progress,
        )
    write_verification_report(report, args.output)
    for record in report.records:
        exceptions = ",".join(record.exception_categories) or "none"
        dates = ",".join(
            f"{basis}={count}" for basis, count in record.date_basis_distribution.items() if count
        )
        print(
            f"{record.company_name}: outcome={record.outcome} jobs={record.job_count} "
            f"pages={record.page_count} missing={record.missing_field_count} "
            f"attempts={record.attempt_count} dates={dates or 'none'} exceptions={exceptions} "
            f"failures={','.join(record.failure_categories) or 'none'} "
            f"anomalies={','.join(record.anomaly_categories) or 'none'}"
        )
    print(f"Wrote sanitized verification report to {args.output}")
    return 0 if report.healthy else 2


def _measure_recency(args: argparse.Namespace) -> int:
    phase_gate = _load_phase_gate("recency_verification", "measure-recency")
    registry = load_company_registry(args.registry)
    profile = load_search_profile(args.profile)
    client = BoundedHttpClient(policy=HttpPolicy(timeout_seconds=args.timeout))
    report = phase_gate.measure_enabled_recency(
        registry,
        _runtime_adapters(client),
        profile,
        source_retry_count=args.source_retries,
    )
    phase_gate.write_recency_report(report, args.output)
    classes = ",".join(f"{key.value}={value}" for key, value in report.company_class_counts.items())
    evidence = ",".join(f"{key}={value}" for key, value in asdict(report.listing_counts).items())
    decisions = ",".join(f"{key}={value}" for key, value in asdict(report.decision_counts).items())
    print(
        f"companies={report.enabled_company_count} listings={report.listing_count} "
        f"identities={report.valid_identity_count} urls={report.valid_url_count}"
    )
    print(f"company_classes={classes}")
    print(f"date_evidence={evidence}")
    print(f"recency_decisions={decisions}")
    print(f"first_seen_available={report.first_seen_available_count}")
    print(f"Wrote sanitized recency report to {args.output}")
    return 0 if report.healthy else 2


def _runtime_adapters(client: BoundedHttpClient) -> AdapterRegistry:
    return AdapterRegistry(
        [
            CustomAdapterRouter(
                [
                    AganithaCareersAdapter(client),
                    AirbnbCareersAdapter(client),
                    AmazonJobsAdapter(client),
                    AppleJobsAdapter(client),
                    AtlassianCareersAdapter(client),
                    AtomicworkWebflowAdapter(client),
                    BookingCareersAdapter(client),
                    DeshawIndiaAdapter(client),
                    GalaxEyeZohoAdapter(client),
                    GnaniCareersAdapter(client),
                    GoogleCareersAdapter(client),
                    IntuitCareersAdapter(client),
                    IndexExchangeCareersAdapter(client),
                    MicrosoftCareersAdapter(client),
                    NaviCareersAdapter(client),
                    PageUpXmlFeedAdapter(client),
                    PcsxCareersAdapter(client),
                    QuadeyeCareersAdapter(client),
                    QureCareersAdapter(client),
                    StripeCareersAdapter(client),
                    SwiggyCareersAdapter(client),
                    TwilioCareersAdapter(client),
                ]
            ),
            AshbyAdapter(client),
            DarwinboxAdapter(client),
            EightfoldAdapter(client),
            FreshteamAdapter(client),
            GreenhouseAdapter(client),
            JobviteAdapter(client),
            LeverAdapter(client),
            OracleCloudAdapter(client),
            RecruiterflowAdapter(client),
            RipplingAdapter(client),
            SenseHqAdapter(client),
            SmartRecruitersAdapter(client),
            SuccessFactorsAdapter(client),
            WorkdayAdapter(client),
        ]
    )


def _filter_jobs(args: argparse.Namespace) -> int:
    registry = load_company_registry(args.registry)
    profile = load_search_profile(args.profile)
    client = BoundedHttpClient(policy=HttpPolicy(timeout_seconds=args.timeout))
    report = collect_listings(
        registry,
        _runtime_adapters(client),
        profile,
        source_retry_count=args.source_retries,
    )
    write_filter_report(report, args.output)
    write_filter_review(report, args.review_output)
    print(
        f"companies={report.enabled_company_count} listings={report.listing_count} "
        f"strict_recent={report.strict_recent_count} "
        f"uncertain={report.uncertain_candidate_count}"
    )
    print(f"roles={json.dumps(report.role_counts, sort_keys=True)}")
    print(f"locations={json.dumps(report.location_counts, sort_keys=True)}")
    print(f"final={json.dumps(report.final_counts, sort_keys=True)}")
    print(f"Wrote sanitized filter report to {args.output}")
    print(f"Wrote H6 review artifact to {args.review_output}")
    return 0 if report.healthy else 2


def _maintain_state(args: argparse.Namespace) -> int:
    if args.state_command == "inspect":
        summary = inspect_state(args.database)
    elif args.state_command == "backup":
        summary = backup_state(args.database, args.output)
    elif args.state_command == "restore":
        summary = restore_state(args.backup, args.output)
    elif args.state_command == "reset":
        before, summary = reset_state(
            args.database,
            args.backup,
            confirmation=args.confirm_database,
            lock_path=args.lock,
        )
        print(
            f"backup={before.database_path} records={before.job_count} "
            f"schema={before.schema_version}"
        )
    elif args.state_command == "prune":
        pruned, summary = prune_descriptions(
            args.database,
            args.backup,
            confirmation=args.confirm_database,
            lock_path=args.lock,
            older_than_days=args.older_than_days,
        )
        print(
            f"pruned={pruned.rows_cleared} row(s) older_than_days={args.older_than_days} "
            f"reclaimed={format_bytes(pruned.bytes_reclaimed)} "
            f"db={format_bytes(pruned.bytes_after)}"
        )
    else:  # pragma: no cover - argparse constrains state commands.
        raise ValueError(f"unknown state command: {args.state_command}")
    print(
        f"database={summary.database_path} schema={summary.schema_version} "
        f"records={summary.job_count} pending={summary.pending_count} "
        f"completed={summary.completed_count} failed={summary.failed_count}"
    )
    if summary.batch_date is not None:
        print(
            f"saved_batch={summary.batch_date} fresh={summary.batch_fresh} "
            f"candidates={summary.batch_candidate_count} pending={summary.batch_pending_count}"
        )
    return 0


def _verify_persistence(args: argparse.Namespace) -> int:
    phase_gate = _load_phase_gate("persistence_verification", "verify-persistence")
    registry = load_company_registry(args.registry)
    profile = load_search_profile(args.profile)
    client = BoundedHttpClient(policy=HttpPolicy(timeout_seconds=args.timeout))
    report = phase_gate.verify_persistence(
        registry,
        _runtime_adapters(client),
        profile,
        database_path=args.database,
        lock_path=args.lock,
        source_retry_count=args.source_retries,
        require_empty=not args.allow_existing,
        pass_count=args.passes,
    )
    phase_gate.write_persistence_report(report, args.output)
    for item in report.passes:
        print(
            f"pass={item.pass_number} listings={item.listing_count} "
            f"retained={item.retained_count} new={item.new_identity_count} "
            f"existing={item.existing_identity_count} healthy={item.source_healthy} "
            f"outcomes={json.dumps(item.source_outcomes, sort_keys=True)}"
        )
        for issue in item.source_issues:
            print(
                f"source_issue company={issue.company_id} adapter={issue.adapter_type} "
                f"outcome={issue.outcome} exceptions={','.join(issue.exception_categories)}"
            )
    print(
        "second_pass_new_companies="
        f"{json.dumps(phase_gate.second_pass_new_companies(report), sort_keys=True)}"
    )
    print(f"Wrote sanitized persistence report to {args.output}")
    return 0 if report.healthy else 2


def _check_llm(args: argparse.Namespace) -> int:
    presence = configuration_presence(dotenv_path=args.dotenv)
    print(f"configured={','.join(presence.configured) or 'none'}")
    print(f"missing={','.join(presence.missing) or 'none'}")
    if not presence.complete:
        return 2
    if args.presence_only:
        return 0
    try:
        result = check_gateway_connectivity(load_gateway_settings(dotenv_path=args.dotenv))
    except GatewayProviderError as error:
        print(f"connectivity=failed error={error}")
        return 2
    print(
        f"connectivity=ok provider={result.provider} "
        f"configured_model={result.configured_model} returned_model={result.returned_model_id}"
    )
    return 0


def _validate_seniority(args: argparse.Namespace) -> int:
    if not 1 <= args.live_limit <= 20:
        raise ValueError("--live-limit must be between 1 and 20")
    phase_gate = _load_phase_gate("seniority_validation", "validate-seniority")
    registry = load_company_registry(args.registry)
    profile = load_search_profile(args.profile)
    evaluation_set = load_seniority_evaluation_set(args.evaluation_set)
    prompt = load_seniority_prompt(args.prompt)
    settings = load_gateway_settings(dotenv_path=args.dotenv)
    budget = UsageBudget(settings.usage_limits)
    evaluator = SeniorityEvaluator(
        client=AmdGatewayClient(settings),
        prompt=prompt,
        model_policy=settings.model_policy,
        budget=budget,
    )
    client = BoundedHttpClient(policy=HttpPolicy(timeout_seconds=args.timeout))
    adapters = _runtime_adapters(client)

    reviewed = phase_gate.run_reviewed_evaluation_set(
        evaluation_set,
        evaluator,
        target_description=profile.seniority.description,
    )
    if args.reuse_live_from is not None:
        reused, candidates, collection_issues = phase_gate.recollect_live_candidates(
            args.reuse_live_from,
            registry,
            adapters,
            profile,
            source_retry_count=args.source_retries,
        )
        if args.live_limit != reused.live_candidate_limit:
            raise ValueError(
                "--live-limit must match the reused report's live_candidate_limit "
                f"({reused.live_candidate_limit})"
            )
        filter_scan_at = reused.filter_scan_at
        enabled_company_count = reused.enabled_company_count
        source_outcomes = reused.source_outcomes
        source_healthy = reused.source_healthy
        retained_count = reused.retained_candidate_count
        explicit_count = reused.explicit_candidate_count
        conditional_count = reused.conditional_candidate_count
    else:
        filter_report = collect_listings(
            registry,
            adapters,
            profile,
            source_retry_count=args.source_retries,
        )
        candidates, collection_issues = phase_gate.collect_live_candidates(
            filter_report,
            registry,
            adapters,
            profile,
            limit=args.live_limit,
        )
        retained_count, explicit_count, conditional_count = phase_gate.retained_role_counts(
            filter_report
        )
        filter_scan_at = filter_report.scan_at
        enabled_company_count = filter_report.enabled_company_count
        source_outcomes = filter_report.outcome_counts
        source_healthy = filter_report.healthy
    live = phase_gate.run_live_candidate_batch(
        candidates,
        evaluator,
        target_description=profile.seniority.description,
    )
    report = phase_gate.Phase8ValidationReport(
        schema_version=1,
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        registry_version=registry.registry_version,
        profile_id=profile.profile_id,
        profile_version=profile.version,
        profile_hash=profile.content_hash,
        evaluation_set_version=evaluation_set.set_version,
        prompt_version=prompt.prompt_version,
        model_policy=settings.model_policy.cache_key,
        filter_scan_at=filter_scan_at,
        enabled_company_count=enabled_company_count,
        source_outcomes=source_outcomes,
        source_healthy=source_healthy,
        retained_candidate_count=retained_count,
        explicit_candidate_count=explicit_count,
        conditional_candidate_count=conditional_count,
        live_candidate_limit=args.live_limit,
        collection_issues=collection_issues,
        reviewed_cases=reviewed,
        live_cases=live,
        quality=phase_gate.quality_metrics(reviewed),
        usage=budget.snapshot,
    )
    phase_gate.write_phase8_validation_report(report, args.output)
    phase_gate.write_h9_review(report, args.review_output)
    print(
        f"reviewed={report.quality.total_count} "
        f"agreement={report.quality.decision_agreement_count} "
        f"accuracy={report.quality.decision_accuracy_percent:.2f}% "
        f"invalid={report.quality.invalid_count} "
        f"threshold_passed={str(report.quality.recommended_threshold_passed).lower()}"
    )
    print(
        f"live={len(report.live_cases)} requested={report.live_candidate_limit} "
        f"requests={report.usage.request_count} "
        f"input_tokens={report.usage.measured_input_tokens} "
        f"output_tokens={report.usage.measured_output_tokens}"
    )
    print(
        f"companies={report.enabled_company_count} "
        f"source_healthy={str(report.source_healthy).lower()} "
        f"outcomes={json.dumps(dict(report.source_outcomes), sort_keys=True)}"
    )
    print(f"Wrote generated validation evidence to {args.output}")
    print(f"Wrote H9 review artifact to {args.review_output}")
    return (
        0
        if report.quality.recommended_threshold_passed
        and report.source_healthy
        and len(report.live_cases) == report.live_candidate_limit
        else 2
    )


def _database_size(path: Path) -> int:
    """Size of the state database on disk, or 0 if it is not there yet.

    Strictly observational, like the rest of cost accounting: a stat failure must never
    turn a completed scan into a reported failure, so it reports zero instead of raising.
    """
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _raw_print_progress(message: str) -> None:
    """Keep long-running scan progress visible even when stdout is redirected."""
    print(message, flush=True)


# The operator watches the progress stream live; the log is what survives an unattended
# run. Both carry the same key=value text so a report and its log line up (9.1).
_print_progress = progress_logger(_raw_print_progress)


def _display_progress(display: ScanDisplay) -> Callable[[str], None]:
    """Route progress through the live display, keeping the log text identical.

    The display is a pure presentation layer: it parses the same key=value strings that
    already go to the log file, so nothing upstream knows a terminal exists and the log
    is byte-identical whether or not anyone is watching.
    """

    def emit(message: str) -> None:
        phase, position, total, outcome = parse_progress(message)
        if total is not None and position is None:
            # "status=started companies=150" -- a new phase with a known step count.
            display.start_phase(phase, total)
            display.log(message)
            return
        if position is not None:
            # Reset the label, counter and ETA clock if this belongs to a new phase, even
            # when that phase never emitted a start line.
            display.ensure_phase(phase, total)
            # This company is done, so stop showing it as in flight -- otherwise the
            # spinner keeps a stale name until the next one starts.
            display.end_item()
            # Use the producer's own position rather than counting messages. Phase 3
            # reports every tenth job, so advancing by one per message pinned the bar at
            # roughly a tenth of real progress for the entire phase.
            display.log(message, outcome=outcome, position=position)
            return
        display.log(message, outcome=outcome)

    return progress_logger(emit)


def _scan(args: argparse.Namespace) -> int:
    """All three daily commands share admission, locked outputs and permanent accounting."""
    display = ScanDisplay(enabled=False if args.plain else None)
    try:
        if args.checkpoint is not None:
            raise CheckpointError(
                "--checkpoint is retired; run a fresh scan to create a SQLite batch"
            )
        if args.discovery_only and (args.command != "scan" or args.resume):
            raise ValueError("--discovery-only is only available with a fresh scan")
        if args.json_output.resolve() == args.markdown_output.resolve():
            raise ValueError("JSON and Markdown output paths must be different")
        if args.enable_expiry and args.no_probe:
            raise ValueError("--enable-expiry requires liveness probing; remove --no-probe")
        registry = load_company_registry(args.registry)
        profile = load_search_profile(args.profile)
        settings = load_gateway_settings(dotenv_path=args.dotenv)
        gateway = AmdGatewayClient(settings)
        budget = UsageBudget(settings.usage_limits)
        evaluator: JobEvaluator
        if args.seniority_only:
            evaluator = SeniorityEvaluator(
                client=gateway,
                prompt=load_seniority_prompt(args.prompt),
                model_policy=settings.model_policy,
                budget=budget,
            )
            print("WARNING: --seniority-only disables the AI/ML relevance gate")
        else:
            evaluator = MergedEvaluator(
                client=gateway,
                prompt=load_merged_prompt(args.merged_prompt),
                model_policy=settings.model_policy,
                budget=budget,
            )
        command = "evaluate" if args.command == "scan" and args.resume else args.command
        client = BoundedHttpClient(
            policy=HttpPolicy(
                timeout_seconds=args.timeout,
                min_interval_seconds=args.min_request_interval,
                max_concurrent_per_host=args.max_concurrent_per_host,
            ),
            on_request=lambda _url: display.tick(),
        )
        adapters = _runtime_adapters(client) if command == "scan" else AdapterRegistry([])
        output_paths: tuple[Path, ...] = ()
        daily_log: Path | None = None

        def admit(day: str, reset: bool) -> None:
            nonlocal output_paths, daily_log
            log_path = configure_logging(
                state_directory=args.log_directory,
                verbose=args.verbose,
                filename=f"scan-{day}.log",
                reset=reset,
            )
            daily_log = log_path
            output_paths = (
                args.json_output.with_name(f"scan-{day}.json"),
                args.markdown_output.with_name(f"scan-{day}.md"),
                args.json_output,
                args.markdown_output,
            )
            if reset:
                for path in set(output_paths):
                    path.unlink(missing_ok=True)
            _LOGGER.info(
                "cli_start command=%s date=%s version=%s log=%s",
                command,
                day,
                __version__,
                log_path,
            )
            print(
                f"Starting {command} date={day} registry={registry.registry_version} "
                f"profile={profile.version} prompt={evaluator.prompt_version} "
                f"report_schema={SCAN_REPORT_SCHEMA_VERSION} state_schema={CURRENT_SCHEMA_VERSION}",
                flush=True,
            )

        def save(result: DailyScanResult) -> None:
            _LOGGER.info(
                "coverage=%s evaluation_complete=%s pending=%s",
                result.report.outcome.value,
                not result.pending_count,
                result.pending_count,
            )
            for path in dict.fromkeys(output_paths):
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
                try:
                    if path.suffix.lower() == ".json" or path in {
                        output_paths[0],
                        args.json_output,
                    }:
                        write_scan_report(result.report, temporary)
                    else:
                        write_scan_markdown(result.report, temporary)
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)

        def account(connection: sqlite3.Connection) -> None:
            # Failed discovery retains only a diagnostic, not partial search information.
            if (
                command == "scan"
                and daily_log is not None
                and connection.execute("SELECT 1 FROM daily_batch").fetchone() is None
            ):
                try:
                    configure_logging(
                        state_directory=args.log_directory,
                        verbose=args.verbose,
                        filename=daily_log.name,
                        reset=True,
                    )
                    _LOGGER.warning("discovery=discarded checkpoint=absent; fresh scan required")
                except OSError:
                    print("Failed to clear discovery log; no evaluation checkpoint was saved.")
            try:
                export_accounting(connection, args.cost_ledger)
            except (OSError, ValueError, sqlite3.Error) as error:
                _LOGGER.warning(
                    "cost_export_failed exception=%s; spending remains in SQLite",
                    type(error).__name__,
                )
                print(
                    "Cost ledger export failed; spending remains in SQLite. "
                    "Use costs to inspect it."
                )

        result = run_daily_scan(
            registry,
            adapters,
            profile,
            evaluator,
            database_path=args.database,
            lock_path=args.lock,
            command=command,
            discovery_only=args.discovery_only,
            source_retry_count=args.source_retries,
            expiry_dry_run=not args.enable_expiry,
            job_probe=None
            if args.no_probe
            else lambda url, listed: probe_job_url(
                url, listed=listed, timeout_seconds=args.timeout
            ),
            connectivity=ConnectivityWaiter(
                policy=ConnectivityPolicy(
                    max_wait_seconds=args.network_wait_minutes * 60,
                    enabled=args.network_wait_minutes > 0,
                )
            ),
            on_item_start=display.begin_item,
            progress=_display_progress(display),
            rates=settings.token_rates,
            on_admitted=admit,
            on_result=save,
            on_finally=account,
        )
        report = result.report
        evaluation_status = (
            "deferred"
            if args.discovery_only
            else "complete"
            if not result.pending_count
            else "incomplete"
        )
        print(
            f"coverage={report.outcome.value} "
            f"evaluation={evaluation_status} "
            f"listings={report.metrics.listing_count} pending={result.pending_count}"
        )
        print(
            f"strict_matches={len(report.matching_jobs)} "
            f"date_uncertain_matches={len(report.date_uncertain_jobs)} "
            f"reviews={len(report.review_candidates)}"
        )
        print(f"Wrote machine-readable report to {args.json_output}")
        print(f"Wrote human-readable report to {args.markdown_output}")
        if args.discovery_only:
            print("Discovery saved. LLM evaluation was deferred; no LLM calls were made.")
        if result.pending_count:
            label = "DEFERRED" if args.discovery_only else "INCOMPLETE"
            print(f"{label}: {result.pending_count} job(s) remain; reason={result.halt_reason}")
            if india_date(datetime.fromisoformat(report.completed_at)) != result.admission_date:
                print("  The batch expired at midnight IST; run a fresh scan.")
            else:
                prefix = "python -m job_finder"
                if args.log_directory != Path("state"):
                    prefix += " --log-directory " + _shell_argument(str(args.log_directory))
                if args.verbose:
                    prefix += " --verbose"
                print(f"  Resume with: {prefix} evaluate{_resume_suffix(args)}")
            print(
                f"  Saved in {args.database}; new invocations allowed until midnight IST "
                f"ending {result.admission_date}"
            )
        return result.exit_code
    except ScanAlreadyRunningError as error:
        print(f"scan=skipped reason=already_running error={error}")
        return 4
    except CheckpointError as error:
        print(f"evaluation=unavailable error={error}")
        print("  Run a fresh scan, or force_reevaluate when only evaluation rules changed.")
        return 5
    except KeyboardInterrupt:
        print("scan=interrupted; use evaluate if discovery completed, otherwise run a fresh scan")
        return 130
    except (OSError, sqlite3.Error, GatewayProviderError, RuntimeError, ValueError) as error:
        print(f"scan=failed error={type(error).__name__}: {error}")
        return 3
    finally:
        display.close()


def _shell_argument(value: str) -> str:
    """Print a safe pasteable argument for the host's usual terminal."""
    return "'" + value.replace("'", "''") + "'" if os.name == "nt" else shlex.quote(value)


def _resume_suffix(args: argparse.Namespace) -> str:
    """Preserve evaluation configuration and output routing, without retired checkpoints."""
    defaults = {
        "registry": Path("config/company_sources.json"),
        "profile": Path("config/search_profile.toml"),
        "prompt": Path("config/seniority_prompt.toml"),
        "merged_prompt": Path("config/merged_prompt.toml"),
        "dotenv": Path(".env"),
        "database": Path("state/jobs.sqlite3"),
        "lock": Path("state/scan.lock"),
        "cost_ledger": DEFAULT_LEDGER_PATH,
        "json_output": Path("reports/latest_scan.json"),
        "markdown_output": Path("reports/latest_scan.md"),
    }
    parts = []
    for name, default in defaults.items():
        value = getattr(args, name, default)
        if value != default:
            parts.append(" --" + name.replace("_", "-") + " " + _shell_argument(str(value)))
    for name in ("seniority_only", "plain"):
        if getattr(args, name, False):
            parts.append(" --" + name.replace("_", "-"))
    return "".join(parts)


def _repair(args: argparse.Namespace) -> int:
    """Build or validate repair evidence without mutating active configuration."""
    if args.repair_command == "build-request":
        request = build_repair_request(
            load_company_registry(args.registry),
            args.verification,
            company_id=args.company_id,
        )
        write_repair_artifact(request, args.output)
        print(
            f"proposal_id={request.proposal_id} company={request.company_id} "
            f"status=inactive output={args.output}"
        )
        return 0
    if args.repair_command == "validate-proposal":
        request = load_repair_request(args.request)
        proposal = load_and_validate_repair_proposal(request, args.proposal)
        write_repair_artifact(proposal, args.output)
        print(
            f"proposal_id={proposal.proposal_id} company={proposal.company_id} "
            f"status={proposal.activation_status} output={args.output}"
        )
        return 0
    if args.repair_command == "test-proposal":
        registry = load_company_registry(args.registry)
        request = load_repair_request(args.request)
        proposal = load_and_validate_repair_proposal(request, args.proposal)
        preview = preview_registry_with_proposal(registry, request, proposal)
        source = next(
            item.source for item in preview.entries if item.source.company_id == request.company_id
        )
        client = BoundedHttpClient(policy=HttpPolicy(timeout_seconds=args.timeout))
        report = verify_adapter_sources(
            preview,
            _runtime_adapters(client),
            source.adapter_type,
            company_ids=(source.company_id,),
            source_retry_count=args.source_retries,
            progress=_print_progress,
        )
        write_verification_report(report, args.output)
        record = report.records[0]
        print(
            f"proposal_id={proposal.proposal_id} company={proposal.company_id} "
            f"status=inactive outcome={record.outcome} jobs={record.job_count} "
            f"pages={record.page_count} output={args.output}"
        )
        return 0 if report.healthy else 2
    raise ValueError(f"unknown repair command: {args.repair_command}")
