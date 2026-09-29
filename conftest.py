"""Pytest configuration for the repository root.

Adds the repository root to ``sys.path`` so that the relocated phase-gate modules under
``scripts/phase_gates/`` remain importable from tests after they were moved out of the
installed ``job_finder`` package (see ``to_change.md`` 6.7 / decision B).

They are deliberately no longer part of the shipped wheel: a ~100-minute idempotency test
and a one-time phase-gate report generator are not library code. They stay runnable and
tested, which is what this file preserves.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parent

if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))
