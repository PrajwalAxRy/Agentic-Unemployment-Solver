"""Apply unambiguous hosted ATS fingerprints to source proposals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from job_finder.core.source_fingerprint import apply_fingerprint_results


def _load(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as stream:
        raw: Any = json.load(stream)
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return raw


def main() -> int:
    """Update proposal adapter classifications without changing approval status."""
    root = Path(__file__).resolve().parents[1]
    proposal_path = root / "data" / "source_discovery_proposals.json"
    revised = apply_fingerprint_results(
        _load(proposal_path),
        _load(root / "diagnostics" / "source_fingerprints.json"),
    )
    proposal_path.write_text(
        json.dumps(revised, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Applied hosted ATS fingerprints to {proposal_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
