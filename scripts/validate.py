"""Run the complete local repository validation suite."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    """Run formatting, linting, type checks, and tests in a fixed order."""
    repository_root = Path(__file__).resolve().parents[1]
    commands = (
        ("ruff format", [sys.executable, "-m", "ruff", "format", "--check", "."]),
        ("ruff lint", [sys.executable, "-m", "ruff", "check", "."]),
        ("mypy", [sys.executable, "-m", "mypy"]),
        ("pytest", [sys.executable, "-m", "pytest"]),
    )

    for label, command in commands:
        print(f"==> {label}", flush=True)
        completed = subprocess.run(command, cwd=repository_root, check=False)
        if completed.returncode != 0:
            return completed.returncode

    print("All validation checks passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
