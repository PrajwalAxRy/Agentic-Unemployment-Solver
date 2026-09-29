"""Logging configuration for the job finder.

Before this module existed, ``import logging`` appeared in **zero** files under ``src/``.
The only observability was ``print()`` -- 39 calls in ``cli.py`` plus a
``progress: Callable[[str], None]`` threaded through the scan. That is why the 2026-09-29
run could report ``outcome: complete`` while 92 percent of description fetches failed, and
why a daily cron job would have rotted silently for weeks (``to_change.md`` 6.1, 9.1).

Design follows the standard library convention:

* **Libraries never configure handlers.** Every module does
  ``logger = logging.getLogger(__name__)`` and nothing else. Only the CLI entry point calls
  :func:`configure_logging`, so importing ``job_finder`` as a library stays silent.
* **stdout stays clean.** Report output goes to stdout; logs go to a rotating file and to
  stderr. Piping a report into a file must not capture log noise.
* **The existing progress channel is preserved, not replaced.** ``progress`` is the
  user-facing channel and callers still see it. :func:`progress_logger` tees each message to
  the log at INFO. The progress strings are already ``key=value``-shaped
  (``phase=source_collection progress=42/150 company=x outcome=success``), so they need no
  reformatting to be greppable.

Level conventions used across the codebase:

===========  ====================================================================
DEBUG        per-job detail; volume is proportional to listings processed
INFO         per-company and per-phase progress; the normal operating narrative
WARNING      recoverable, and recorded in the report -- the scan continues
ERROR        a company failed outright; other companies are unaffected
CRITICAL     the scan cannot continue
===========  ====================================================================
"""

from __future__ import annotations

import logging
import logging.handlers
from collections.abc import Callable
from pathlib import Path

DEFAULT_LOG_FILENAME = "scan.log"
_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5
_FILE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s %(message)s"
_STDERR_FORMAT = "%(levelname)-8s %(name)s %(message)s"


def configure_logging(
    *,
    state_directory: Path,
    verbose: bool = False,
    stderr_level: int = logging.WARNING,
) -> Path:
    """Configure root logging for a command-line run. Returns the log file path.

    Call once, from the CLI only. Safe to call repeatedly: existing handlers installed by a
    previous call are removed first so tests and repeated invocations do not accumulate
    duplicate sinks.

    ``verbose`` lowers the file sink to DEBUG and the stderr sink to INFO.
    """
    log_directory = state_directory / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / DEFAULT_LOG_FILENAME

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
    root.addHandler(file_handler)

    stderr_handler = logging.StreamHandler()
    stderr_handler.setLevel(logging.INFO if verbose else stderr_level)
    stderr_handler.setFormatter(logging.Formatter(_STDERR_FORMAT))
    root.addHandler(stderr_handler)

    return log_path


def progress_logger(
    printer: Callable[[str], None],
    *,
    logger_name: str = "job_finder.progress",
) -> Callable[[str], None]:
    """Wrap a progress callback so every message is also logged at INFO.

    The progress channel is what the operator watches live; the log is what survives to be
    read after an unattended run. Both get the same text, so a report and its log line up.
    """
    logger = logging.getLogger(logger_name)

    def emit(message: str) -> None:
        logger.info("%s", message)
        printer(message)

    return emit
