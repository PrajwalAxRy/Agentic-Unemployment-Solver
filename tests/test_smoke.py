"""Package and command-line smoke tests."""

from __future__ import annotations

import pytest

import job_finder
from job_finder.cli import build_parser, main


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
