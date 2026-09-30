"""Round-trip and safety tests for the budget-halt resume checkpoint."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from job_finder.checkpoint import (
    DEFAULT_CHECKPOINT_PATH,
    SCHEMA_VERSION,
    CheckpointError,
    CheckpointRow,
    ResumeCheckpoint,
    assert_resumable,
    read_checkpoint,
    write_checkpoint,
)
from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.filters.locations import LocationDecision, LocationFilterResult
from job_finder.filters.roles import RoleDecision, RoleFilterResult


def make_job(*, published: datetime | date | None) -> NormalizedJob:
    return NormalizedJob(
        schema_version=1,
        company_id="adobe",
        source_type="workday",
        external_job_id="R12345",
        title_original="Machine Learning Engineer",
        title_normalized="machine learning engineer",
        location_original="Bengaluru, India",
        location_normalized=("bengaluru",),
        published_at=published,
        published_at_raw="2026-09-01",
        date_basis=DateBasis.PUBLISHED,
        canonical_url="https://example.com/jobs/R12345",
        source_metadata={"req_id": "R12345"},
    )


def make_row(*, published: datetime | date | None = None) -> CheckpointRow:
    return CheckpointRow(
        company_id="adobe",
        title_original="Machine Learning Engineer",
        location_original="Bengaluru, India",
        canonical_url="https://example.com/jobs/R12345",
        candidate_section="strict_recent",
        role=RoleFilterResult(
            decision=RoleDecision.CONDITIONAL_DESCRIPTION,
            reason_code="engineering_function",
            reason="engineering title requires description evidence",
            family_id="ml",
            matched_term="engineer",
        ),
        location=LocationFilterResult(
            decision=LocationDecision.PASS,
            reason_code="india_city",
            reason="Bengaluru is an India location",
            matched_locations=("bengaluru",),
            work_modes=("onsite",),
        ),
        normalized_job=make_job(published=published or datetime(2026, 9, 1, tzinfo=UTC)),
    )


def make_checkpoint(**overrides: object) -> ResumeCheckpoint:
    base: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(UTC),
        "run_id": "scan-20260930T134411Z-4c43aba7",
        "scan_at": "2026-09-30T13:44:11.923558+00:00",
        "profile_version": "1.1.2",
        "prompt_version": "1.0.0",
        "model_policy": "openai:gpt-5.6-luna:1",
        "evaluated_before_halt": 140,
        "reason": "estimated LLM input-token limit reached",
        "rows": (make_row(),),
    }
    base.update(overrides)
    return ResumeCheckpoint(**base)  # type: ignore[arg-type]


def test_round_trip_preserves_every_field_the_evaluator_reads(tmp_path: Path) -> None:
    path = tmp_path / "resume.json"
    original = make_checkpoint()

    write_checkpoint(original, path)
    loaded = read_checkpoint(path)

    assert loaded.run_id == original.run_id
    assert loaded.evaluated_before_halt == 140
    assert len(loaded.rows) == 1
    row, expected = loaded.rows[0], original.rows[0]
    assert row == expected, "a lossy round trip would silently change what gets judged"


def test_a_bare_date_does_not_become_a_datetime(tmp_path: Path) -> None:
    """Some adapters report a date, not a datetime, and lifecycle treats them differently.

    isoformat/fromisoformat alone loses this: a date round-trips into a midnight datetime.
    """
    path = tmp_path / "resume.json"
    write_checkpoint(make_checkpoint(rows=(make_row(published=date(2026, 9, 1)),)), path)

    published = read_checkpoint(path).rows[0].normalized_job.published_at

    assert not isinstance(published, datetime)
    assert published == date(2026, 9, 1)


def test_a_stale_checkpoint_is_refused(tmp_path: Path) -> None:
    """Resuming onto old data spends budget on postings that may already have closed."""
    stale = make_checkpoint(created_at=datetime.now(UTC) - timedelta(hours=30))

    with pytest.raises(CheckpointError, match="old"):
        assert_resumable(
            stale,
            profile_version="1.1.2",
            prompt_version="1.0.0",
            model_policy="openai:gpt-5.6-luna:1",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("profile_version", "1.2.0"),
        ("prompt_version", "1.1.0"),
        ("model_policy", "openai:gpt-6-luna:1"),
    ],
)
def test_configuration_drift_is_refused(field: str, value: str) -> None:
    """Verdicts judged under different rules must not be merged into one report."""
    current = {
        "profile_version": "1.1.2",
        "prompt_version": "1.0.0",
        "model_policy": "openai:gpt-5.6-luna:1",
    }
    current[field] = value

    with pytest.raises(CheckpointError, match="configuration changed"):
        assert_resumable(make_checkpoint(), **current)  # type: ignore[arg-type]


def test_a_missing_checkpoint_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(CheckpointError, match="no checkpoint"):
        read_checkpoint(tmp_path / "absent.json")


def test_a_corrupt_checkpoint_is_not_silently_ignored(tmp_path: Path) -> None:
    """Falling back to a full scan without saying so turns resume into four silent hours."""
    path = tmp_path / "resume.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(CheckpointError, match="could not be read"):
        read_checkpoint(path)


def test_an_unknown_schema_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "resume.json"
    write_checkpoint(make_checkpoint(), path)
    path.write_text(
        path.read_text(encoding="utf-8").replace('"schema_version": 1', '"schema_version": 99', 1),
        encoding="utf-8",
    )

    with pytest.raises(CheckpointError, match="schema_version"):
        read_checkpoint(path)


def test_write_is_atomic_and_leaves_no_temporary_behind(tmp_path: Path) -> None:
    path = tmp_path / "resume.json"
    write_checkpoint(make_checkpoint(), path)
    write_checkpoint(make_checkpoint(evaluated_before_halt=300), path)

    assert read_checkpoint(path).evaluated_before_halt == 300
    assert list(tmp_path.iterdir()) == [path], "a leftover .tmp would confuse operators"


def test_the_resume_command_echoes_non_default_paths() -> None:
    """The printed command has to work exactly as shown.

    A halted scan still writes a report and exits 0, so this notice is the only signal
    the run was incomplete. Printing a command that silently targets the default database
    when the operator used a different one would be worse than printing nothing.
    """
    import argparse

    from job_finder.cli import _resume_suffix

    default = argparse.Namespace(
        checkpoint=DEFAULT_CHECKPOINT_PATH, database=Path("state/jobs.sqlite3")
    )
    assert _resume_suffix(default) == "", "the plain command needs no flags"

    custom = argparse.Namespace(
        checkpoint=Path("state/other.json"), database=Path("state/alt.sqlite3")
    )
    suffix = _resume_suffix(custom)
    assert "--checkpoint state/other.json" in suffix
    assert "--database state/alt.sqlite3" in suffix
