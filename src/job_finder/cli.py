"""Command-line entry point for the job finder."""

from __future__ import annotations

import argparse
import importlib
import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from job_finder import __version__
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
from job_finder.checkpoint import DEFAULT_CHECKPOINT_PATH, CheckpointError
from job_finder.collection import (
    collect_listings,
    write_filter_report,
    write_filter_review,
)
from job_finder.core.company_registry import load_company_registry
from job_finder.core.job_probe import JobProbeResult, probe_job_url
from job_finder.core.search_profile import load_search_profile
from job_finder.core.source_contracts import AdapterType
from job_finder.cost import (
    DEFAULT_LEDGER_PATH,
    append_to_ledger,
    daily_totals,
    format_bytes,
    format_cost_line,
    price_run,
    read_ledger,
    summarise,
)
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
    resume_from_checkpoint,
    run_manual_scan,
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
    state_prune = state_subparsers.add_parser(
        "prune",
        help="Clear stored description text for jobs not seen recently. Keeps the rows.",
    )
    state_prune.add_argument("--database", type=Path, default=Path("state/jobs.sqlite3"))
    state_prune.add_argument("--backup", type=Path, required=True)
    state_prune.add_argument("--confirm-database", required=True)
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
        "--resume",
        action="store_true",
        help=(
            "Skip collection and filtering; evaluate the rows left over by a run that "
            "halted on budget. Requires a checkpoint newer than 24h."
        ),
    )
    scan.add_argument(
        "--checkpoint",
        type=Path,
        default=DEFAULT_CHECKPOINT_PATH,
        help="Where the resume checkpoint is written and read.",
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
    # The CLI is the only place that configures logging; library imports stay silent.
    log_path = configure_logging(
        state_directory=args.log_directory,
        verbose=args.verbose,
    )
    _LOGGER.info(
        "cli_start command=%s version=%s log=%s",
        args.command,
        __version__,
        log_path,
    )
    if args.command == "verify-sources":
        return _verify_sources(args)
    if args.command == "measure-recency":
        return _measure_recency(args)
    if args.command == "filter-jobs":
        return _filter_jobs(args)
    if args.command == "state":
        return _maintain_state(args)
    if args.command == "verify-persistence":
        return _verify_persistence(args)
    if args.command == "check-llm":
        return _check_llm(args)
    if args.command == "validate-seniority":
        return _validate_seniority(args)
    if args.command == "scan":
        return _scan(args)
    if args.command == "repair":
        return _repair(args)
    if args.command == "costs":
        return _costs(args)
    return 0


def _costs(args: argparse.Namespace) -> int:
    """Print the per-day cost history recorded by previous scans."""
    history = read_ledger(args.ledger)
    if not history:
        print(f"costs=none ledger={args.ledger}")
        print("  No runs recorded yet. Cost is written after each scan completes.")
        return 0

    rows = daily_totals(history)
    shown = rows if args.days <= 0 else rows[-args.days :]
    totals = summarise(history)
    currency = str(totals["currency"])

    print(
        f"{'day':<12}{'runs':>6}{'evaluated':>11}{'cost (' + currency + ')':>14}"
        f"{'added':>11}{'db total':>11}"
    )
    for row in shown:
        print(
            f"{row['day']:<12}{row['runs']:>6}{row['evaluated']:>11}{float(row['cost']):>14.2f}"
            f"{format_bytes(int(row['bytes_added'])):>11}"  # type: ignore[call-overload]
            f"{format_bytes(int(row['bytes_total'])):>11}"  # type: ignore[call-overload]
        )
    print()
    print(
        f"total={currency} {float(totals['total_cost'] or 0):.2f} "
        f"over {totals['distinct_days']} day(s), "
        f"{totals['runs']} run(s), {totals['total_evaluated']} job(s) evaluated"
    )
    if totals["cost_per_evaluated_job"] is not None:
        print(f"per_evaluated_job={currency} {float(totals['cost_per_evaluated_job']):.4f}")
    if totals["mean_cost_per_day"] is not None:
        # Flagged as an extrapolation rather than printed as "your monthly bill": the
        # first run evaluates the whole backlog and later ones only new postings, so a
        # mean taken across both overstates the steady state.
        print(
            f"mean_per_day={currency} {float(totals['mean_cost_per_day']):.2f} "
            f"-> ~{currency} {float(totals['projected_30_day'] or 0):.2f}/30d "
            "(extrapolated; early backlog runs inflate this)"
        )
    if totals["unpriced_runs"]:
        print(
            f"note: {totals['unpriced_runs']} run(s) had no configured rates and are "
            "excluded from the totals above"
        )
    return 0


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
    """Run one user-facing manual scan and write both report formats."""
    try:
        registry = load_company_registry(args.registry)
        profile = load_search_profile(args.profile)
        settings = load_gateway_settings(dotenv_path=args.dotenv)
        gateway = AmdGatewayClient(settings)
        budget = UsageBudget(settings.usage_limits)

        # The merged call (2.5) is the default: it is the only thing that judges AI/ML
        # relevance, and 2.2a widened the title filter so far that without it every
        # engineering title in India reaches the report. --seniority-only restores the
        # tuned single-purpose prompt, which stays available precisely so a regression in
        # the merged judgment can be backed out without a code change.
        evaluator: JobEvaluator
        if args.seniority_only:
            prompt = load_seniority_prompt(args.prompt)
            evaluator = SeniorityEvaluator(
                client=gateway,
                prompt=prompt,
                model_policy=settings.model_policy,
                budget=budget,
            )
            print("WARNING: --seniority-only disables the AI/ML relevance gate (2.3)")
        else:
            merged = load_merged_prompt(args.merged_prompt)
            evaluator = MergedEvaluator(
                client=gateway,
                prompt=merged,
                model_policy=settings.model_policy,
                budget=budget,
            )
            prompt = merged  # type: ignore[assignment]

        display = ScanDisplay(enabled=False if args.plain else None)
        client = BoundedHttpClient(
            policy=HttpPolicy(
                timeout_seconds=args.timeout,
                min_interval_seconds=args.min_request_interval,
                max_concurrent_per_host=args.max_concurrent_per_host,
            ),
            # One tick per outgoing request. This is what distinguishes a slow company
            # from a hung one on boards that take dozens of paginated requests.
            on_request=lambda _url: display.tick(),
        )
        print(
            f"Starting scan with registry={registry.registry_version} "
            f"profile={profile.version} prompt={prompt.prompt_version} "
            f"report_schema={SCAN_REPORT_SCHEMA_VERSION} state_schema={CURRENT_SCHEMA_VERSION}",
            flush=True,
        )
        if args.enable_expiry and args.no_probe:
            raise ValueError(
                "--enable-expiry cannot be combined with --no-probe: the probe is the "
                "only guard against a truncated listing closing live jobs (to_change.md 10.F)"
            )

        connectivity = ConnectivityWaiter(
            policy=ConnectivityPolicy(
                max_wait_seconds=args.network_wait_minutes * 60,
                enabled=args.network_wait_minutes > 0,
            )
        )

        def _probe(url: str, listed: bool) -> JobProbeResult | None:
            return probe_job_url(url, listed=listed, timeout_seconds=args.timeout)

        # Sampled before the lock is taken so it reflects the file this run inherited.
        # Zero on a first run, when the database does not exist yet.
        db_bytes_before = _database_size(args.database)

        try:
            if args.resume:
                report = resume_from_checkpoint(
                    registry,
                    _runtime_adapters(client),
                    profile,
                    evaluator,
                    database_path=args.database,
                    lock_path=args.lock,
                    checkpoint_path=args.checkpoint,
                    progress=_display_progress(display),
                )
            else:
                report = run_manual_scan(
                    registry,
                    _runtime_adapters(client),
                    profile,
                    evaluator,
                    database_path=args.database,
                    lock_path=args.lock,
                    source_retry_count=args.source_retries,
                    expiry_dry_run=not args.enable_expiry,
                    job_probe=None if args.no_probe else _probe,
                    connectivity=connectivity,
                    on_item_start=display.begin_item,
                    progress=_display_progress(display),
                    checkpoint_path=args.checkpoint,
                )
        finally:
            # Restore the cursor even on Ctrl-C or a crash mid-scan.
            display.close()
    except ScanAlreadyRunningError as error:
        # Benign under cron: a previous run is still going. Distinct exit code so an
        # overlapping schedule is not alerted on like a real failure (to_change.md 6.2, 9.3).
        _LOGGER.warning("scan=skipped reason=already_running detail=%s", error)
        print(f"scan=skipped reason=already_running error={error}")
        return 4
    except CheckpointError as error:
        # Distinct from a scan failure: nothing went wrong, the checkpoint is just absent,
        # stale, or built under different rules. The remedy is always a full scan.
        _LOGGER.warning("scan=resume_unavailable reason=%s", error)
        print(f"scan=resume_unavailable error={error}")
        # Every CheckpointError means the same remedy, so say it rather than leaving the
        # operator to infer it from the message.
        print("  Run a full scan instead:  python -m job_finder scan")
        return 5
    except (GatewayProviderError, RuntimeError, ValueError) as error:
        _LOGGER.exception("scan=failed exception=%s reason=%s", type(error).__name__, error)
        print(f"scan=failed error={type(error).__name__}: {error}")
        return 3

    write_scan_report(report, args.json_output)
    write_scan_markdown(report, args.markdown_output)
    print(
        f"scan={report.outcome.value} companies={report.metrics.attempted_company_count} "
        f"successful={report.metrics.successful_company_count} "
        f"empty={report.metrics.valid_empty_company_count} "
        f"failed={report.metrics.failed_company_count} listings={report.metrics.listing_count}"
    )
    print(
        f"new_identities={report.metrics.new_identity_count} "
        f"duplicates={report.metrics.duplicate_suppressed_count} "
        f"strict_matches={len(report.matching_jobs)} "
        f"date_uncertain_matches={len(report.date_uncertain_jobs)} "
        f"reviews={len(report.review_candidates)}"
    )
    timing: dict[str, Any] = dict(report.timing) if report.timing else {}
    if timing.get("company_count"):
        print(
            f"source_timing total={timing['total_seconds']}s "
            f"mean={timing['mean_seconds']}s median={timing['median_seconds']}s "
            f"min={timing['min_seconds']}s max={timing['max_seconds']}s "
            f"companies={timing['company_count']}"
        )
        # Naming the slow companies is the actionable part: it turns "the scan took 40
        # minutes" into "Adobe took 4 of them".
        for item in list(timing.get("slowest", []))[:3]:
            print(
                f"  slowest: {item['company_id']} ({item['adapter_type']}) "
                f"{item['seconds']}s, {item['listings']} listings"
            )

    lifecycle: dict[str, Any] = dict(report.lifecycle) if report.lifecycle else {}
    if lifecycle:
        mode = "dry_run" if lifecycle["dry_run"] else "enforcing"
        verb = "would_close" if lifecycle["dry_run"] else "closed"
        count = lifecycle["would_close"] if lifecycle["dry_run"] else lifecycle["closed"]
        print(
            f"lifecycle={mode} sightings={lifecycle['sightings']} "
            f"absences={lifecycle['absences']} probes={lifecycle['probes_fired']} "
            f"{verb}={count}"
        )
        # 5.1: the dry-run week is only over when all four checks have been observed.
        # Printing what is still unmet is the difference between "we ran it for a week"
        # and "we verified it".
        if lifecycle["dry_run"] and not lifecycle["checklist_satisfied"]:
            for item in list(lifecycle["unmet_requirements"]):
                print(f"  dry_run_unmet: {item}")
        reappearance: dict[str, Any] = dict(lifecycle["reappearance"])
        flagged: list[str] = list(reappearance["sources_needing_review"])
        if flagged:
            print(f"  reappearance_review: {', '.join(flagged)}")

    print(f"Wrote machine-readable report to {args.json_output}")
    print(f"Wrote human-readable report to {args.markdown_output}")

    # Last thing on screen, deliberately. A halted scan still writes a full report and
    # exits successfully, so without this it reads as a completed run that simply found
    # fewer jobs -- which is how the 2026-09-30 halt went unnoticed until the database was
    # inspected by hand.
    # Cost accounting is strictly observational: a failure to record it must never turn a
    # completed scan into a reported failure.
    try:
        cost = price_run(
            run_id=report.run_id,
            completed_at=report.completed_at,
            model_policy=report.model_policy,
            prompt_version=report.prompt_version,
            evaluated=report.metrics.llm_evaluated_count,
            cache_hits=report.metrics.llm_cache_hit_count,
            request_count=report.usage.request_count,
            input_tokens=report.usage.measured_input_tokens,
            output_tokens=report.usage.measured_output_tokens,
            rates=settings.token_rates,
            db_bytes_before=db_bytes_before,
            db_bytes_total=_database_size(args.database),
        )
        append_to_ledger(cost, args.cost_ledger)
        print(format_cost_line(cost))
    except OSError as error:
        _LOGGER.warning("cost_ledger_write_failed path=%s error=%s", args.cost_ledger, error)

    if report.metrics.llm_budget_halted_count:
        remaining = report.metrics.llm_budget_halted_count
        print()
        print(
            f"INCOMPLETE: the run budget ran out with {remaining} job(s) still "
            "unevaluated. They are saved, not lost."
        )
        print(f"  Resume with:  python -m job_finder scan --resume{_resume_suffix(args)}")
        print(f"  Checkpoint:   {args.checkpoint} (valid for 24h)")
    return report.outcome.exit_code


def _resume_suffix(args: argparse.Namespace) -> str:
    """Echo back any non-default paths, so the printed command actually works as shown."""
    parts = []
    if args.checkpoint != DEFAULT_CHECKPOINT_PATH:
        parts.append(f" --checkpoint {args.checkpoint}")
    if args.database != Path("state/jobs.sqlite3"):
        parts.append(f" --database {args.database}")
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
