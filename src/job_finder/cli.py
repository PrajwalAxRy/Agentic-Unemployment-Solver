"""Command-line entry point for the job finder."""

from __future__ import annotations

import argparse
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""
    args = build_parser().parse_args(argv)
    if args.command == "verify-sources":
        return _verify_sources(args)
    if args.command == "measure-recency":
        return _measure_recency(args)
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
