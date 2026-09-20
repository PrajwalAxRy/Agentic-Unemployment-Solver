"""Apply tracked Phase 2 source quality corrections to the proposal batch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from job_finder.core.source_quality import (
    apply_quality_corrections,
    load_quality_corrections,
)


def _load_json(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as stream:
        raw: Any = json.load(stream)
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return raw


def main() -> int:
    """Apply replacements and conservative conflict downgrades in place."""
    root = Path(__file__).resolve().parents[1]
    proposal_path = root / "data" / "source_discovery_proposals.json"
    correction_path = root / "data" / "source_quality_corrections.json"
    revised = apply_quality_corrections(
        _load_json(proposal_path),
        load_quality_corrections(correction_path),
    )
    proposal_path.write_text(
        json.dumps(revised, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Applied source quality corrections from {correction_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
