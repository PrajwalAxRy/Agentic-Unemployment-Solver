"""CLI integration verifies locked daily replacement, standalone evaluation and exit codes."""

import json
import logging
from dataclasses import replace

import pytest

import job_finder.cli as cli
from job_finder.adapters.base import AdapterRegistry
from job_finder.daily_scan import run_daily_scan
from job_finder.matching.evaluator import UsageLimits
from job_finder.matching.openai_client import load_gateway_settings
from job_finder.persistence.locking import ScanLock
from tests.matching.test_openai_client import configured_environment
from tests.test_scan import (
    PROFILE,
    SCAN_AT,
    StubAdapter,
    StubLLMClient,
    decision,
    job,
    registry,
    source,
)


@pytest.fixture
def command(tmp_path, monkeypatch):
    state = {
        "client": StubLLMClient([decision(True)]),
        "max_requests": 20,
        "listings": (job("healthy", "1", "ML Engineer", "3+ years of experience"),),
    }
    settings = load_gateway_settings(
        environment=configured_environment(), dotenv_path=tmp_path / "absent.env"
    )
    monkeypatch.setattr(cli, "load_company_registry", lambda path: registry(source("healthy")))
    monkeypatch.setattr(cli, "load_search_profile", lambda path: PROFILE)
    monkeypatch.setattr(
        cli,
        "load_gateway_settings",
        lambda **kwargs: replace(
            settings, usage_limits=UsageLimits(state["max_requests"], 1000000, 10000, 200)
        ),
    )
    monkeypatch.setattr(cli, "AmdGatewayClient", lambda settings: state["client"])
    monkeypatch.setattr(
        cli,
        "_runtime_adapters",
        lambda client: AdapterRegistry([StubAdapter({"healthy": state["listings"]})]),
    )

    def frozen(*args, **kwargs):
        return run_daily_scan(*args, **kwargs, clock=lambda: SCAN_AT, scan_at=SCAN_AT)

    monkeypatch.setattr(cli, "run_daily_scan", frozen)

    def invoke(name="scan", *extra):
        return cli.main(
            [
                "--log-directory",
                str(tmp_path / "state"),
                name,
                "--database",
                str(tmp_path / "jobs.sqlite3"),
                "--lock",
                str(tmp_path / "scan.lock"),
                "--json-output",
                str(tmp_path / "out/latest.json"),
                "--markdown-output",
                str(tmp_path / "out/latest.md"),
                "--cost-ledger",
                str(tmp_path / "costs.jsonl"),
                "--seniority-only",
                "--no-probe",
                "--plain",
                *extra,
            ]
        )

    yield state, invoke
    for handler in list(logging.getLogger().handlers):
        logging.getLogger().removeHandler(handler)
        handler.close()


def test_cli_commands_replace_daily_artifacts_and_evaluate_appends_log(command, tmp_path):
    state, invoke = command
    assert invoke() == 0
    log = tmp_path / "state/logs/scan-2026-09-23.log"
    with log.open("a") as stream:
        stream.write("synthetic earlier-log marker\n")
    state["client"] = StubLLMClient([])
    assert invoke("evaluate") == 0
    assert "earlier-log marker" in log.read_text()
    payload = json.loads((tmp_path / "out/scan-2026-09-23.json").read_text())
    assert len(payload["matching_jobs"]) == 1
    state["client"] = StubLLMClient([decision(False)])
    assert invoke("force_reevaluate") == 0
    assert "earlier-log marker" not in log.read_text()
    payload = json.loads((tmp_path / "out/latest.json").read_text())
    assert not payload["matching_jobs"]
    state["client"] = StubLLMClient([])
    assert invoke() == 0
    assert len(list((tmp_path / "state/logs").glob("scan-*.log"))) == 1
    assert len(list((tmp_path / "out").glob("scan-*.json"))) == 1


def test_busy_lock_does_not_touch_logs_or_reports(command, tmp_path):
    state, invoke = command
    assert invoke() == 0
    log = tmp_path / "state/logs/scan-2026-09-23.log"
    before_log = log.read_bytes()
    before_report = (tmp_path / "out/latest.json").read_bytes()
    state["client"] = StubLLMClient([])
    with ScanLock(tmp_path / "scan.lock"):
        assert invoke() == 4
    assert log.read_bytes() == before_log
    assert (tmp_path / "out/latest.json").read_bytes() == before_report


def test_legacy_checkpoint_flag_is_rejected_without_changing_outputs(command, tmp_path):
    _, invoke = command
    assert invoke() == 0
    before = (tmp_path / "out/latest.json").read_bytes()
    assert invoke("scan", "--checkpoint", str(tmp_path / "legacy.json")) == 5
    assert (tmp_path / "out/latest.json").read_bytes() == before


def test_budget_exit_code_and_scan_resume_alias(command, tmp_path):
    state, invoke = command
    state["max_requests"] = 1
    state["listings"] = tuple(
        job("healthy", str(i), "ML Engineer", "3+ years of experience " + str(i)) for i in range(2)
    )
    assert invoke() == 6
    state["client"] = StubLLMClient([decision(True)])
    assert invoke("scan", "--resume") == 0
    payload = json.loads((tmp_path / "out/latest.json").read_text())
    assert len(payload["matching_jobs"]) == 2
    assert payload["evaluation_complete"] is True


def test_costs_does_not_change_daily_log(command, tmp_path, capsys):
    _, invoke = command
    assert invoke() == 0
    log = tmp_path / "state/logs/scan-2026-09-23.log"
    before = log.read_bytes()
    assert (
        cli.main(
            [
                "--log-directory",
                str(tmp_path / "state"),
                "costs",
                "--database",
                str(tmp_path / "jobs.sqlite3"),
                "--ledger",
                str(tmp_path / "costs.jsonl"),
            ]
        )
        == 0
    )
    assert log.read_bytes() == before
    assert "unknown=" in capsys.readouterr().out


def test_printed_resume_command_preserves_seniority_and_custom_routing(command, tmp_path, capsys):
    import shlex

    state, invoke = command
    state["max_requests"] = 1
    state["listings"] = tuple(
        job("healthy", str(i), "ML Engineer", "3+ years of experience " + str(i)) for i in range(2)
    )
    assert invoke() == 6
    output = capsys.readouterr().out
    printed = next(
        line.split("Resume with: ", 1)[1] for line in output.splitlines() if "Resume with:" in line
    )
    state["client"] = StubLLMClient([decision(True)])
    assert cli.main(shlex.split(printed)[3:]) == 0
    assert len(json.loads((tmp_path / "out/latest.json").read_text())["matching_jobs"]) == 2


def test_failed_discovery_clears_reports_and_keeps_only_failure_log(command, tmp_path, monkeypatch):
    state, invoke = command
    assert invoke() == 0
    monkeypatch.setattr(
        cli,
        "_runtime_adapters",
        lambda client: AdapterRegistry([StubAdapter({}, failed={"healthy"})]),
    )
    state["client"] = StubLLMClient([])
    assert invoke("scan", "--source-retries", "0") == 3
    log = (tmp_path / "state/logs/scan-2026-09-23.log").read_text()
    assert "phase=source_collection" not in log
    assert "discovery=discarded" in log
    assert not (tmp_path / "out/latest.json").exists()
    assert not (tmp_path / "out/scan-2026-09-23.json").exists()
    assert invoke("evaluate") == 5


def test_halt_after_midnight_prints_fresh_scan_guidance(command, monkeypatch, capsys):
    from datetime import UTC, datetime

    state, invoke = command
    state["max_requests"] = 1
    state["listings"] = tuple(
        job("healthy", str(i), "ML Engineer", "3+ years of experience " + str(i)) for i in range(2)
    )
    times = iter(
        [datetime(2026, 9, 23, 18, 29, tzinfo=UTC)]
        + [datetime(2026, 9, 23, 18, 31, tzinfo=UTC)] * 20
    )
    monkeypatch.setattr(
        cli,
        "run_daily_scan",
        lambda *args, **kwargs: run_daily_scan(
            *args, **kwargs, clock=lambda: next(times), scan_at=SCAN_AT
        ),
    )
    assert invoke() == 6
    output = capsys.readouterr().out
    assert "expired at midnight" in output
    assert "Resume with:" not in output
