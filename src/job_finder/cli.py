"""Command-line entry point for the job finder."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from job_finder import __version__
from job_finder.adapters.ashby import AshbyAdapter
from job_finder.adapters.base import AdapterRegistry
from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy
from job_finder.core.company_registry import load_company_registry
from job_finder.core.source_contracts import AdapterType
from job_finder.verification import verify_adapter_sources, write_verification_report


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
    verify.add_argument("--adapter", choices=(AdapterType.ASHBY.value,), required=True)
    verify.add_argument("--company-id", action="append", default=[])
    verify.add_argument("--registry", type=Path, default=Path("config/company_sources.json"))
    verify.add_argument(
        "--output",
        type=Path,
        default=Path("reports/source_verification.json"),
    )
    verify.add_argument("--timeout", type=float, default=15.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""
    args = build_parser().parse_args(argv)
    if args.command == "verify-sources":
        return _verify_sources(args)
    return 0


def _verify_sources(args: argparse.Namespace) -> int:
    registry = load_company_registry(args.registry)
    policy = HttpPolicy(timeout_seconds=args.timeout)
    adapters = AdapterRegistry([AshbyAdapter(BoundedHttpClient(policy=policy))])
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
