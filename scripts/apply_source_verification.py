"""Merge sanitized probe evidence into provisional source proposals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from job_finder.core.discovery_verification import apply_verification_results


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        payload: Any = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def main() -> int:
    """Apply evidence while preserving disabled, provisional source states."""
    repository_root = Path(__file__).resolve().parents[1]
    proposal_path = repository_root / "data" / "source_discovery_proposals.json"
    verification_path = repository_root / "diagnostics" / "source_discovery_verification.json"
    revised = apply_verification_results(
        _load_json(proposal_path),
        _load_json(verification_path),
    )
    proposal_path.write_text(
        json.dumps(revised, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Applied sanitized verification evidence to {proposal_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
