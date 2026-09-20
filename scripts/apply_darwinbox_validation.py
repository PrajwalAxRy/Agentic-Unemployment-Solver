"""Apply a complete healthy Darwinbox verification report to tracked proposals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from job_finder.core.adapter_validation import apply_darwinbox_validation


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        payload: Any = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    proposal_path = root / "data" / "source_discovery_proposals.json"
    report_path = root / "reports" / "darwinbox_full_verification.json"
    revised = apply_darwinbox_validation(_load(proposal_path), _load(report_path))
    proposal_path.write_text(
        json.dumps(revised, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Applied complete Darwinbox validation evidence to {proposal_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
