"""Package and command-line smoke tests."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

import job_finder
from job_finder import cli as cli_module
from job_finder.cli import build_parser, main
from job_finder.matching.openai_client import REQUIRED_ENVIRONMENT_VARIABLES
from job_finder.scan import run_manual_scan


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


def test_cli_scan_call_matches_run_manual_scan_signature() -> None:
    """The CLI must not pass arguments ``run_manual_scan`` cannot accept.

    Regression test for a real outage: ``cli.py`` passed ``checkpoint_path`` to both
    ``resume_from_checkpoint`` and ``run_manual_scan``, but only the former accepted it.
    Every plain ``job_finder scan`` therefore died with ``TypeError`` before contacting a
    single company, while ``--resume`` kept working -- which is why it went unnoticed.

    The existing suite missed it because every test calls ``run_manual_scan`` directly,
    so the ``cli.py`` -> ``scan.py`` seam was never exercised. This binds the CLI's call
    site to the real signature without needing network, an LLM, or a database.
    """
    signature = inspect.signature(run_manual_scan)

    for name in ("checkpoint_path", "database_path", "lock_path", "progress"):
        assert name in signature.parameters, f"run_manual_scan lost parameter {name!r}"

    source = inspect.getsource(cli_module._scan)
    scan_call = source.split("run_manual_scan(", 1)
    assert len(scan_call) == 2, "cli no longer calls run_manual_scan; update this test"

    # Keywords the CLI hands to run_manual_scan, read straight off the call site.
    passed = set(re.findall(r"^\s+(\w+)=", scan_call[1].split("            )", 1)[0], re.M))
    unsupported = passed - set(signature.parameters)
    assert not unsupported, (
        f"cli.py passes {sorted(unsupported)} to run_manual_scan, which does not accept "
        "them -- a plain scan would raise TypeError before collection"
    )


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
