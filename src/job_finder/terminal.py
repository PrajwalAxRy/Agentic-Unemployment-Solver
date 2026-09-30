"""Live terminal rendering for a scan: progress bar, ETA, and a per-company log.

Deliberately no dependency. ``rich`` and ``tqdm`` would both do this better, but minimal
dependencies is a standing choice in this project (the audit called it out as one of the
things worth not breaking), and a progress bar is not worth a dependency.

Two things happen at once, and both matter:

* the **scrolling log** keeps every company visible as it completes, which is what you
  watch to spot a source going wrong mid-run
* the **status bar** is redrawn in place on the last line, so total progress, rate and ETA
  are always on screen without burying the log

The bar is written to ``stderr``. ``stdout`` stays clean for report output, exactly as the
logging setup already requires -- piping a scan to a file must not capture escape codes.

Everything degrades safely. If stderr is not a TTY (piped, redirected, CI, or a terminal
that cannot handle it) the bar is suppressed entirely and only the plain log lines remain,
which is precisely the behaviour before this existed.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TextIO

# All green, as requested. Outcome is still distinguishable, but by *shade* and by the
# marker glyph rather than by hue: bright green for success, mid for a warning, dim for a
# failure. A failed company must not read identically to a successful one at a glance --
# the ✗ marker carries that even where the shades are close.
_RESET = "\x1b[0m"
_DIM = "\x1b[2m"
_BOLD = "\x1b[1m"
_GREEN = "\x1b[38;5;41m"
_BRIGHT_GREEN = "\x1b[38;5;83m"
_PALE_GREEN = "\x1b[38;5;114m"
_MID_GREEN = "\x1b[38;5;71m"
_DEEP_GREEN = "\x1b[38;5;29m"
_GREY = "\x1b[38;5;244m"

_CLEAR_LINE = "\x1b[2K\r"
_HIDE_CURSOR = "\x1b[?25l"
_SHOW_CURSOR = "\x1b[?25h"

_FILLED = "█"
_PARTIAL = "▓"
_EMPTY = "░"


def supports_colour(stream: TextIO) -> bool:
    """Whether it is safe to write ANSI escapes to ``stream``.

    ``NO_COLOR`` is honoured (see no-color.org) because a user who has asked every tool on
    their machine to stop emitting escapes means this one too.
    """
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("JOB_FINDER_NO_COLOR"):
        return False
    if not hasattr(stream, "isatty") or not stream.isatty():
        return False
    if sys.platform == "win32":
        # Windows Terminal and PowerShell 7 set this; the legacy console does not and
        # would print the raw escape codes.
        return bool(os.environ.get("WT_SESSION") or os.environ.get("TERM"))
    return os.environ.get("TERM", "") not in ("", "dumb")


def _format_duration(seconds: float) -> str:
    if seconds < 0 or seconds != seconds:  # negative or NaN
        return "--:--"
    if seconds >= 3600:
        hours, remainder = divmod(int(seconds), 3600)
        return f"{hours}h{remainder // 60:02d}m"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"


@dataclass
class ScanDisplay:
    """Renders scan progress as a live status bar above a scrolling company log."""

    stream: TextIO = field(default_factory=lambda: sys.stderr)
    enabled: bool | None = None
    width: int | None = None
    now: Callable[[], float] = time.monotonic

    _started: float = field(default=0.0, init=False)
    _phase: str = field(default="", init=False)
    _total: int = field(default=0, init=False)
    _done: int = field(default=0, init=False)
    _bar_visible: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.enabled is None:
            self.enabled = supports_colour(self.stream)
        self._started = self.now()

    # -- lifecycle ---------------------------------------------------------

    def start_phase(self, phase: str, total: int) -> None:
        """Begin a phase with a known number of steps."""
        self._phase = phase
        self._total = max(0, total)
        self._done = 0
        self._started = self.now()
        if self.enabled:
            self.stream.write(_HIDE_CURSOR)
            self.stream.flush()

    def close(self) -> None:
        """Clear the bar and restore the cursor. Safe to call more than once."""
        if self.enabled and self._bar_visible:
            self.stream.write(_CLEAR_LINE)
        if self.enabled:
            self.stream.write(_SHOW_CURSOR)
            self.stream.flush()
        self._bar_visible = False

    def __enter__(self) -> ScanDisplay:
        return self

    def __exit__(self, *_: object) -> None:
        # Always restore the cursor, including on Ctrl-C. Leaving a terminal with a
        # hidden cursor after a crash is a genuinely annoying thing to do to someone.
        self.close()

    # -- output ------------------------------------------------------------

    def ensure_phase(self, phase: str, total: int | None) -> None:
        """Switch phases if this message belongs to a different one.

        The display must not depend on every producer remembering to emit a
        ``status=started`` line first. deterministic_filter did not, so the bar kept the
        previous phase's label and stayed pinned at 100% -- with a stale ETA -- for the
        whole filter pass. Detecting the change here makes the display correct for any
        future phase whether or not it announces itself.
        """
        if not phase or phase == self._phase:
            return
        self.start_phase(phase, total or 0)

    def log(self, line: str, *, outcome: str | None = None, advance: int = 0) -> None:
        """Print one completed-company line, then redraw the bar beneath it.

        ``advance`` is applied *before* the redraw rather than in a separate call. Two
        reasons, both visible in a real run: the bar was being redrawn twice per company,
        and the counter trailed the log line by one -- the first company printed above a
        bar still reading 0/150.
        """
        if advance:
            self._advance_counter(advance)
        if not self.enabled:
            print(line, file=self.stream, flush=True)
            return
        self.stream.write(_CLEAR_LINE)
        self.stream.write(self._colour_line(line, outcome) + "\n")
        self._bar_visible = False
        self._redraw()

    def advance(self, count: int = 1) -> None:
        """Move the bar without printing a line."""
        self._advance_counter(count)
        self._redraw()

    def _advance_counter(self, count: int) -> None:
        self._done = min(self._total, self._done + count) if self._total else self._done + count

    def _redraw(self) -> None:
        if not self.enabled or not self._total:
            return
        self.stream.write(_CLEAR_LINE + self._render_bar())
        self.stream.flush()
        self._bar_visible = True

    # -- rendering ---------------------------------------------------------

    def _terminal_width(self) -> int:
        if self.width is not None:
            return self.width
        return shutil.get_terminal_size(fallback=(100, 24)).columns

    def _render_bar(self) -> str:
        fraction = self._done / self._total if self._total else 0.0
        elapsed = self.now() - self._started
        rate = self._done / elapsed if elapsed > 0 and self._done else 0.0
        remaining = (self._total - self._done) / rate if rate > 0 else float("nan")

        # Reserve room for the text, then give whatever is left to the bar, with a floor
        # so a narrow terminal degrades to a small bar rather than a broken line.
        counts = f"{self._done}/{self._total}"
        stats = (
            f"{fraction * 100:5.1f}%  {counts:>9}  "
            f"{_format_duration(elapsed)} elapsed  "
            f"ETA {_format_duration(remaining)}"
        )
        label = self._phase.replace("_", " ")
        bar_width = max(10, self._terminal_width() - len(stats) - len(label) - 8)

        filled = int(bar_width * fraction)
        # A partial block for the in-flight step, so the bar visibly moves on long
        # companies rather than looking frozen for minutes at a time.
        partial = _PARTIAL if filled < bar_width and self._done < self._total else ""
        empty = _EMPTY * max(0, bar_width - filled - len(partial))

        return (
            f"{_BOLD}{_GREEN}{label}{_RESET} "
            f"{_BRIGHT_GREEN}{_FILLED * filled}{_PALE_GREEN}{partial}"
            f"{_DIM}{_GREY}{empty}{_RESET} "
            f"{_PALE_GREEN}{stats}{_RESET}"
        )

    def _colour_line(self, line: str, outcome: str | None) -> str:
        """Tint one log line by outcome, and dim the key=value noise.

        Every shade is green. The marker glyph is what actually distinguishes outcomes --
        ✓ / ! / ✗ survive colourblindness, a monochrome terminal, and a log file, none of
        which a hue would.
        """
        tint = {
            "success": _BRIGHT_GREEN,
            "empty": _PALE_GREEN,
            "partial": _MID_GREEN,
            "suspicious": _MID_GREEN,
            "blocked": _DEEP_GREEN,
            "failed": _DEEP_GREEN,
        }.get(outcome or "", _PALE_GREEN)

        marker = {
            "success": "✓",
            "empty": "·",
            "partial": "!",
            "suspicious": "!",
            "blocked": "✗",
            "failed": "✗",
        }.get(outcome or "", "›")

        return f"{tint}{marker}{_RESET} {_DIM}{line}{_RESET}"


def parse_progress(message: str) -> tuple[str, int | None, int | None, str | None]:
    """Pull phase, position, total and outcome out of a progress string.

    The progress strings are already ``key=value`` shaped (9.1 kept them that way so they
    are greppable in the log). Reading them here means the display is a pure presentation
    layer -- no producer has to know a terminal exists, and the log file is unchanged.
    """
    fields = dict(
        part.split("=", 1) for part in message.split() if "=" in part and part.count("=") >= 1
    )
    phase = fields.get("phase", "")
    outcome = fields.get("outcome")

    position: int | None = None
    total: int | None = None
    raw = fields.get("progress")
    if raw and "/" in raw:
        head, _, tail = raw.partition("/")
        if head.isdigit() and tail.isdigit():
            position, total = int(head), int(tail)
    elif fields.get("companies", "").isdigit():
        total = int(fields["companies"])
    elif fields.get("retained", "").isdigit():
        total = int(fields["retained"])

    return phase, position, total, outcome
