"""Live terminal display (progress bar, ETA, coloured company log).

The property that matters most is the one that is easy to lose: **the log text is
unchanged**. The display parses the same key=value progress strings that already go to the
log file, so a scan piped to a file, run in CI, or inspected afterwards looks exactly as
it did before this existed.
"""

from __future__ import annotations

import io

import pytest

from job_finder.terminal import ScanDisplay, parse_progress, supports_colour


class _FakeTty(io.StringIO):
    """A StringIO that claims to be a terminal."""

    def isatty(self) -> bool:
        return True


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "phase=source_collection status=started companies=150",
            ("source_collection", None, 150, None),
        ),
        (
            "phase=source_collection progress=42/150 company=glean outcome=success listings=133",
            ("source_collection", 42, 150, "success"),
        ),
        (
            "phase=source_collection progress=7/150 company=x outcome=failed listings=0",
            ("source_collection", 7, 150, "failed"),
        ),
        (
            "phase=candidate_evaluation status=started retained=87",
            ("candidate_evaluation", None, 87, None),
        ),
        ("phase=lifecycle mode=dry_run sightings=3", ("lifecycle", None, None, None)),
    ],
)
def test_progress_strings_are_parsed(
    message: str, expected: tuple[str, int | None, int | None, str | None]
) -> None:
    assert parse_progress(message) == expected


def test_a_non_tty_gets_plain_lines_only() -> None:
    """Piped, redirected, or CI output must be byte-identical to before.

    This is the whole safety story: escape codes in a log file or a pipe would be worse
    than having no progress bar at all.
    """
    stream = io.StringIO()  # not a tty
    display = ScanDisplay(stream=stream)

    display.start_phase("source_collection", 3)
    display.log("phase=source_collection progress=1/3 company=glean outcome=success")
    display.advance()
    display.close()

    output = stream.getvalue()
    assert output == "phase=source_collection progress=1/3 company=glean outcome=success\n"
    assert "\x1b[" not in output, "no escape codes may reach a non-tty"


def test_a_tty_gets_a_bar_and_keeps_every_log_line() -> None:
    """Both halves at once: the scrolling log and the redrawn bar."""
    stream = _FakeTty()
    display = ScanDisplay(stream=stream, enabled=True, width=100)

    display.start_phase("source_collection", 3)
    for index in (1, 2, 3):
        display.log(f"phase=source_collection progress={index}/3 company=c{index}")
        display.advance()
    display.close()

    output = stream.getvalue()
    for index in (1, 2, 3):
        assert f"company=c{index}" in output, "every company must stay visible"
    assert "\x1b[" in output
    assert "█" in output, "the bar should have drawn"
    assert "ETA" in output


def test_the_bar_reports_progress_and_an_eta() -> None:
    clock = iter([0.0, 0.0, 10.0, 10.0, 10.0])
    stream = _FakeTty()
    display = ScanDisplay(stream=stream, enabled=True, width=100, now=lambda: next(clock, 10.0))

    display.start_phase("source_collection", 10)
    display.advance(2)  # 2 of 10 in 10 seconds -> 40s remaining
    rendered = stream.getvalue()

    assert "20.0%" in rendered
    assert "2/10" in rendered
    assert "ETA 00:40" in rendered


def test_outcome_drives_the_marker_so_failures_stand_out() -> None:
    """Colouring everything green would make a failed company look successful."""
    stream = _FakeTty()
    display = ScanDisplay(stream=stream, enabled=True, width=100)
    display.start_phase("source_collection", 2)

    display.log("company=a outcome=success", outcome="success")
    display.log("company=b outcome=failed", outcome="failed")

    output = stream.getvalue()
    assert "✓" in output
    assert "✗" in output


def test_close_restores_the_cursor_and_is_idempotent() -> None:
    """A hidden cursor left behind after a crash is a genuinely annoying bug."""
    stream = _FakeTty()
    display = ScanDisplay(stream=stream, enabled=True, width=80)
    display.start_phase("source_collection", 1)

    display.close()
    display.close()

    assert "\x1b[?25h" in stream.getvalue()


def test_context_manager_restores_the_cursor_on_error() -> None:
    stream = _FakeTty()

    with pytest.raises(RuntimeError):
        with ScanDisplay(stream=stream, enabled=True, width=80) as display:
            display.start_phase("source_collection", 5)
            raise RuntimeError("scan blew up")

    assert "\x1b[?25h" in stream.getvalue()


def test_a_narrow_terminal_still_renders() -> None:
    """Degrade to a small bar rather than a broken line."""
    stream = _FakeTty()
    display = ScanDisplay(stream=stream, enabled=True, width=40)

    display.start_phase("source_collection", 10)
    display.advance(5)

    assert "50.0%" in stream.getvalue()


def test_no_color_environment_variable_is_honoured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Someone who asked every tool to stop emitting escapes meant this one too."""
    monkeypatch.setenv("NO_COLOR", "1")

    assert supports_colour(_FakeTty()) is False


def test_zero_total_does_not_divide_by_zero() -> None:
    stream = _FakeTty()
    display = ScanDisplay(stream=stream, enabled=True, width=80)

    display.start_phase("source_collection", 0)
    display.advance()
    display.close()

    assert "ZeroDivision" not in stream.getvalue()


def test_a_new_phase_resets_the_label_and_counter() -> None:
    """The gap that shipped: deterministic_filter emitted no status=started line.

    The bar kept the previous phase's label and stayed pinned at 100% with a stale ETA for
    the entire filter pass. The display must not depend on producers remembering to
    announce themselves.
    """
    stream = _FakeTty()
    display = ScanDisplay(stream=stream, enabled=True, width=100)

    display.start_phase("source_collection", 3)
    for index in (1, 2, 3):
        display.log(f"phase=source_collection progress={index}/3 company=c{index}", advance=1)

    # A new phase arriving with no start line, exactly as deterministic_filter does.
    display.ensure_phase("deterministic_filter", 3)
    display.log("phase=deterministic_filter progress=1/3 company=c1 seconds=0.4", advance=1)

    rendered = stream.getvalue()
    tail = rendered[rendered.rindex("\n") :]
    assert "deterministic filter" in tail, "the label must follow the new phase"
    assert "1/3" in tail, "the counter must reset rather than stay at 3/3"
    assert "100.0%" not in tail, "the bar must not stay pinned from the previous phase"


def test_repeating_the_same_phase_does_not_reset_progress() -> None:
    """ensure_phase must be idempotent, since it is called on every message."""
    stream = _FakeTty()
    display = ScanDisplay(stream=stream, enabled=True, width=100)
    display.start_phase("source_collection", 10)

    display.log("phase=source_collection progress=1/10 company=a", advance=1)
    display.ensure_phase("source_collection", 10)
    display.log("phase=source_collection progress=2/10 company=b", advance=1)

    tail = stream.getvalue()
    assert "2/10" in tail, "progress must survive a same-phase check"


def test_filter_progress_carries_its_own_timing() -> None:
    """The deterministic filter reports per-company seconds like source collection."""
    phase, position, total, outcome = parse_progress(
        "phase=deterministic_filter progress=7/150 company=glean retained=2 reviews=1 seconds=0.412"
    )

    assert phase == "deterministic_filter"
    assert (position, total) == (7, 150)
    assert outcome is None
