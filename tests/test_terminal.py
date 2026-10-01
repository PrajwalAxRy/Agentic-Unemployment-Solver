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
    """ETA is median-based, over per-item durations.

    A multi-step advance covers that many items, so 10s across two of them is a 5s
    median -- not a 10s one. This previously asserted 01:20, charging the whole batch to
    a single item; that is the same inflation that made candidate_evaluation's ETA ~10x
    too long, since it advances ten jobs at a time.
    """
    clock = [0.0]
    stream = _FakeTty()
    display = ScanDisplay(stream=stream, enabled=True, width=100, now=lambda: clock[0])

    display.start_phase("source_collection", 10)
    clock[0] = 10.0
    display.advance(2)
    rendered = stream.getvalue()

    assert "20.0%" in rendered
    assert "2/10" in rendered
    assert "ETA 00:40" in rendered, "8 remaining at the observed 5s-per-item median"


def test_eta_uses_the_median_so_one_slow_item_does_not_dominate() -> None:
    """The real failure: 3 companies at ~0.05s then Adobe at 5 minutes gave 'ETA 4h39m'.

    A mean over that mix predicts a number that describes no actual company. The median
    stays stable when the slow one lands, which is the property that matters.
    """
    clock = [0.0]
    stream = _FakeTty()
    display = ScanDisplay(stream=stream, enabled=True, width=110, now=lambda: clock[0])
    display.start_phase("deterministic_filter", 150)

    for duration in (0.032, 0.109, 0.0):
        clock[0] += duration
        display.advance()
    fast_eta = _last_eta(stream.getvalue())

    clock[0] += 300.0  # Adobe
    display.advance()
    after_slow = _last_eta(stream.getvalue())

    assert fast_eta.startswith("00:"), f"a few fast items must not predict hours: {fast_eta}"
    assert "h" not in after_slow, f"one slow item must not dominate the estimate: {after_slow}"


def _last_eta(rendered: str) -> str:
    import re

    return re.findall(r"ETA\s+(\S+)", re.sub(r"\x1b\[[0-9;]*m", "", rendered))[-1]


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

    with (
        pytest.raises(RuntimeError),
        ScanDisplay(stream=stream, enabled=True, width=80) as display,
    ):
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


def test_a_long_company_shows_activity_while_the_bar_is_frozen() -> None:
    """The 'it looks stuck' fix.

    A Workday board takes ~28 paginated requests, during which the outer bar cannot move
    at all. The spinner and request counter are what distinguish working from hung.
    """
    stream = _FakeTty()
    display = ScanDisplay(stream=stream, enabled=True, width=110)
    display.start_phase("source_collection", 150)
    display.log("phase=source_collection progress=1/150 company=glean", advance=1)

    display.begin_item("adobe")
    for _ in range(5):
        display.tick()

    tail = stream.getvalue()[stream.getvalue().rindex("\n") :]
    assert "adobe" in tail
    assert "5 req" in tail
    assert "1/150" in tail, "the outer bar is still frozen, which is the point"


def test_the_spinner_actually_turns() -> None:
    """A static glyph would look exactly as stuck as no glyph at all."""
    stream = _FakeTty()
    display = ScanDisplay(stream=stream, enabled=True, width=110)
    display.start_phase("source_collection", 10)
    display.begin_item("adobe")

    # The spinner is at the END of the line, so compare whole redraws rather than a
    # prefix -- slicing the first 40 characters shows only the static bar.
    frames = []
    previous = 0
    for _ in range(4):
        display.tick()
        rendered = stream.getvalue()
        frames.append(rendered[previous:])
        previous = len(rendered)

    assert len(set(frames)) > 1, "the spinner must change between ticks"


def test_completing_a_company_clears_the_in_flight_label() -> None:
    """Otherwise the spinner keeps a stale name until the next company starts."""
    stream = _FakeTty()
    display = ScanDisplay(stream=stream, enabled=True, width=110)
    display.start_phase("source_collection", 10)

    display.begin_item("adobe")
    display.tick()
    display.end_item()
    display.log("phase=source_collection progress=1/10 company=adobe", advance=1)

    tail = stream.getvalue()[stream.getvalue().rindex("\n") :]
    assert "req" not in tail, "the in-flight suffix must be gone once the company is done"


def test_beginning_a_new_company_resets_its_counter() -> None:
    stream = _FakeTty()
    display = ScanDisplay(stream=stream, enabled=True, width=110)
    display.start_phase("source_collection", 10)

    display.begin_item("adobe")
    for _ in range(9):
        display.tick()
    display.begin_item("cartesia")
    display.tick()

    tail = stream.getvalue()[stream.getvalue().rindex("\r") :]
    assert "cartesia" in tail
    assert "1 req" in tail, "the request count belongs to the new company, not the old"


def test_a_batched_producer_moves_the_bar_by_its_real_position() -> None:
    """The bug: candidate_evaluation reports every tenth job, the bar advanced by one.

    3,677 retained jobs produce ~368 messages, so counting messages left the bar reading
    ~10% at the end of the phase before snapping to 100%. The producer's own position is
    authoritative.
    """
    stream = _FakeTty()
    display = ScanDisplay(stream=stream, enabled=True, width=110)
    display.start_phase("candidate_evaluation", 3677)

    for position in (1, 10, 20, 30):
        display.log(
            f"phase=candidate_evaluation progress={position}/3677 company=adobe",
            position=position,
        )

    tail = stream.getvalue()[stream.getvalue().rindex("\n") :]
    assert "30/3677" in tail, "the counter must track jobs, not messages"
    assert "0.8%" in tail, "30 of 3677 is 0.8%, not the 0.1% that message-counting gave"


def test_a_batched_producer_does_not_inflate_the_eta() -> None:
    """The ETA half of the same bug.

    A message covering ten jobs took ten jobs' wall time. Charging all of it to a single
    item made the median ten times too large, and that median is then multiplied by an
    outstanding count that was itself ten times too big.
    """
    clock = [0.0]
    stream = _FakeTty()
    display = ScanDisplay(stream=stream, enabled=True, width=110, now=lambda: clock[0])
    display.start_phase("candidate_evaluation", 100)

    # Ten jobs per message, one second per job.
    for position in (10, 20, 30):
        clock[0] += 10.0
        display.set_position(position)

    # 70 jobs remain at a true 1s/job median.
    assert _last_eta(stream.getvalue()) == "01:10"


def test_position_never_runs_backwards_or_past_the_total() -> None:
    """Defensive: a duplicate or stale message must not rewind a live bar."""
    stream = _FakeTty()
    display = ScanDisplay(stream=stream, enabled=True, width=110)
    display.start_phase("candidate_evaluation", 50)

    display.set_position(30)
    display.set_position(999)
    assert "50/50" in stream.getvalue()[stream.getvalue().rindex("\r") :], "clamp to the total"


def test_the_cli_routes_batched_progress_through_the_real_position() -> None:
    """Covers the wiring, not just the display.

    The bug lived in _display_progress passing advance=1 per message, while ScanDisplay
    was perfectly capable of taking a position. Testing only the display would have gone
    on missing it.
    """
    from job_finder.cli import _display_progress

    stream = _FakeTty()
    display = ScanDisplay(stream=stream, enabled=True, width=110)
    emit = _display_progress(display)

    emit("phase=candidate_evaluation status=started retained=3677")
    emit("phase=candidate_evaluation progress=1/3677 company=adobe")
    emit("phase=candidate_evaluation progress=500/3677 company=adobe")

    tail = stream.getvalue()[stream.getvalue().rindex("\n") :]
    assert "500/3677" in tail, "the bar must follow the jobs, not the message count"


def test_activity_never_reaches_a_non_tty() -> None:
    """Ticks must not spam a log file or a pipe with thousands of lines."""
    stream = io.StringIO()
    display = ScanDisplay(stream=stream)

    display.start_phase("source_collection", 10)
    display.begin_item("adobe")
    for _ in range(50):
        display.tick()

    assert stream.getvalue() == "", "a non-tty must see nothing from ticks"
