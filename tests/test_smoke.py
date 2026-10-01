"""Package and command-line smoke tests."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import job_finder
from job_finder import cli as cli_module
from job_finder.cli import build_parser, main
from job_finder.daily_scan import run_daily_scan
from job_finder.matching.openai_client import REQUIRED_ENVIRONMENT_VARIABLES


def test_package_imports_with_version() -> None:
    assert job_finder.__version__ == "0.1.0"


def test_cli_reports_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--version"])

    assert error.value.code == 0
    assert capsys.readouterr().out.strip() == "job-finder 0.1.0"


def test_cli_accepts_workday_source_verification() -> None:
    args = build_parser().parse_args(["verify-sources", "--adapter", "workday"])

    assert args.adapter == "workday"


def test_cli_accepts_custom_source_verification() -> None:
    args = build_parser().parse_args(["verify-sources", "--adapter", "custom"])

    assert args.adapter == "custom"


def test_cli_accepts_darwinbox_source_verification() -> None:
    args = build_parser().parse_args(["verify-sources", "--adapter", "darwinbox"])

    assert args.adapter == "darwinbox"


def test_cli_accepts_eightfold_source_verification() -> None:
    args = build_parser().parse_args(["verify-sources", "--adapter", "eightfold"])

    assert args.adapter == "eightfold"


def test_cli_accepts_oracle_cloud_source_verification() -> None:
    args = build_parser().parse_args(["verify-sources", "--adapter", "oracle_cloud"])

    assert args.adapter == "oracle_cloud"


def test_cli_accepts_successfactors_source_verification() -> None:
    args = build_parser().parse_args(["verify-sources", "--adapter", "successfactors"])

    assert args.adapter == "successfactors"


def test_cli_accepts_jobvite_source_verification() -> None:
    args = build_parser().parse_args(["verify-sources", "--adapter", "jobvite"])

    assert args.adapter == "jobvite"


def test_cli_accepts_enabled_registry_source_verification() -> None:
    args = build_parser().parse_args(["verify-sources", "--all-enabled"])

    assert args.all_enabled is True
    assert args.adapter is None


def test_cli_accepts_full_registry_recency_measurement() -> None:
    args = build_parser().parse_args(["measure-recency", "--output", "reports/test_recency.json"])

    assert args.command == "measure-recency"
    assert args.profile == Path("config/search_profile.toml")
    assert args.output == Path("reports/test_recency.json")
    assert args.source_retries == 2


def test_cli_state_reset_requires_backup_and_confirmation() -> None:
    args = build_parser().parse_args(
        [
            "state",
            "reset",
            "--backup",
            "state/jobs-before-reset.sqlite3",
            "--confirm-database",
            r"C:\resolved\state\jobs.sqlite3",
        ]
    )

    assert args.state_command == "reset"
    assert args.database == Path("state/jobs.sqlite3")
    assert args.backup == Path("state/jobs-before-reset.sqlite3")


def test_cli_accepts_two_pass_persistence_verification() -> None:
    args = build_parser().parse_args(["verify-persistence", "--allow-existing", "--passes", "1"])

    assert args.command == "verify-persistence"
    assert args.database == Path("state/phase7_validation.sqlite3")
    assert args.output == Path("reports/phase7_persistence_verification.json")
    assert args.allow_existing is True
    assert args.passes == 1


def test_cli_accepts_guarded_seniority_validation() -> None:
    args = build_parser().parse_args(
        [
            "validate-seniority",
            "--live-limit",
            "6",
            "--reuse-live-from",
            "reports/prior.json",
        ]
    )

    assert args.command == "validate-seniority"
    assert args.live_limit == 6
    assert args.reuse_live_from == Path("reports/prior.json")
    assert args.evaluation_set == Path("config/seniority_evaluation_set.json")
    assert args.review_output == Path("docs/reviews/h9_seniority_quality_review.md")


def test_scan_parser_defaults() -> None:
    args = build_parser().parse_args(["scan"])

    assert args.command == "scan"
    assert args.database == Path("state/jobs.sqlite3")
    assert args.lock == Path("state/scan.lock")
    assert args.json_output == Path("reports/latest_scan.json")
    assert args.markdown_output == Path("reports/latest_scan.md")
    assert args.source_retries == 2


def test_cli_scan_call_matches_daily_scan_signature() -> None:
    """Keep regression coverage for the previously broken CLI/orchestration seam."""
    import ast

    signature = inspect.signature(run_daily_scan)
    tree = ast.parse(inspect.getsource(cli_module._scan))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "run_daily_scan"
    ]
    assert len(calls) == 1
    passed = {keyword.arg for keyword in calls[0].keywords}
    assert passed <= set(signature.parameters)


def test_cli_reports_only_missing_llm_variable_names(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in REQUIRED_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)

    exit_code = main(["check-llm", "--presence-only", "--dotenv", str(tmp_path / "absent.env")])

    output = capsys.readouterr().out
    assert exit_code == 2
    assert "configured=none" in output
    assert "LLM_GATEWAY_KEY" in output
    assert "Bearer" not in output
