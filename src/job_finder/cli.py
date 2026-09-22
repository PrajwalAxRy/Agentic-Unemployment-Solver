"""Command-line entry point for the job finder."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from job_finder import __version__
from job_finder.adapters.ashby import AshbyAdapter
from job_finder.adapters.base import AdapterRegistry
from job_finder.adapters.darwinbox import DarwinboxAdapter
from job_finder.adapters.eightfold import EightfoldAdapter
from job_finder.adapters.greenhouse import GreenhouseAdapter
from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy
from job_finder.adapters.jobvite import JobviteAdapter
from job_finder.adapters.lever import LeverAdapter
from job_finder.adapters.oracle_cloud import OracleCloudAdapter
from job_finder.adapters.smartrecruiters import SmartRecruitersAdapter
from job_finder.adapters.successfactors import SuccessFactorsAdapter
from job_finder.adapters.workday import WorkdayAdapter
from job_finder.core.company_registry import load_company_registry
from job_finder.core.search_profile import load_search_profile
from job_finder.core.source_contracts import AdapterType
from job_finder.filter_verification import (
    verify_filters,
    write_filter_report,
    write_filter_review,
)
from job_finder.matching.openai_client import (
    OpenAIProviderError,
    check_openai_connectivity,
    configuration_presence,
    load_openai_settings,
)
from job_finder.persistence.maintenance import (
    backup_state,
    inspect_state,
    reset_state,
    restore_state,
)
from job_finder.persistence_verification import (
    second_pass_new_companies,
    verify_persistence,
    write_persistence_report,
)
from job_finder.recency_verification import measure_enabled_recency, write_recency_report
from job_finder.verification import (
    verify_adapter_sources,
    verify_enabled_sources,
    write_verification_report,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level command-line parser."""
    parser = argparse.ArgumentParser(prog="job-finder")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
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
            AdapterType.DARWINBOX.value,
            AdapterType.EIGHTFOLD.value,
            AdapterType.GREENHOUSE.value,
            AdapterType.JOBVITE.value,
            AdapterType.LEVER.value,
            AdapterType.ORACLE_CLOUD.value,
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""
    args = build_parser().parse_args(argv)
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
    return 0


def _verify_sources(args: argparse.Namespace) -> int:
    registry = load_company_registry(args.registry)
    policy = HttpPolicy(timeout_seconds=args.timeout)
    client = BoundedHttpClient(policy=policy)
    adapters = _runtime_adapters(client)
    if args.all_enabled:
        if args.company_id:
            raise ValueError("--company-id cannot be combined with --all-enabled")
        report = verify_enabled_sources(registry, adapters)
    else:
        report = verify_adapter_sources(
            registry,
            adapters,
            AdapterType(args.adapter),
            company_ids=args.company_id,
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
            f"dates={dates or 'none'} exceptions={exceptions}"
        )
    print(f"Wrote sanitized verification report to {args.output}")
    return 0 if report.healthy else 2


def _measure_recency(args: argparse.Namespace) -> int:
    registry = load_company_registry(args.registry)
    profile = load_search_profile(args.profile)
    client = BoundedHttpClient(policy=HttpPolicy(timeout_seconds=args.timeout))
    report = measure_enabled_recency(
        registry,
        _runtime_adapters(client),
        profile,
        source_retry_count=args.source_retries,
    )
    write_recency_report(report, args.output)
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
            AshbyAdapter(client),
            DarwinboxAdapter(client),
            EightfoldAdapter(client),
            GreenhouseAdapter(client),
            JobviteAdapter(client),
            LeverAdapter(client),
            OracleCloudAdapter(client),
            SmartRecruitersAdapter(client),
            SuccessFactorsAdapter(client),
            WorkdayAdapter(client),
        ]
    )


def _filter_jobs(args: argparse.Namespace) -> int:
    registry = load_company_registry(args.registry)
    profile = load_search_profile(args.profile)
    client = BoundedHttpClient(policy=HttpPolicy(timeout_seconds=args.timeout))
    report = verify_filters(
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
    else:  # pragma: no cover - argparse constrains state commands.
        raise ValueError(f"unknown state command: {args.state_command}")
    print(
        f"database={summary.database_path} schema={summary.schema_version} "
        f"records={summary.job_count} pending={summary.pending_count} "
        f"completed={summary.completed_count} failed={summary.failed_count}"
    )
    return 0


def _verify_persistence(args: argparse.Namespace) -> int:
    registry = load_company_registry(args.registry)
    profile = load_search_profile(args.profile)
    client = BoundedHttpClient(policy=HttpPolicy(timeout_seconds=args.timeout))
    report = verify_persistence(
        registry,
        _runtime_adapters(client),
        profile,
        database_path=args.database,
        lock_path=args.lock,
        source_retry_count=args.source_retries,
        require_empty=not args.allow_existing,
        pass_count=args.passes,
    )
    write_persistence_report(report, args.output)
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
        f"second_pass_new_companies={json.dumps(second_pass_new_companies(report), sort_keys=True)}"
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
        result = check_openai_connectivity(load_openai_settings(dotenv_path=args.dotenv))
    except OpenAIProviderError as error:
        print(f"connectivity=failed error={error}")
        return 2
    print(
        f"connectivity=ok provider={result.provider} "
        f"configured_model={result.configured_model} returned_model={result.returned_model_id}"
    )
    return 0
