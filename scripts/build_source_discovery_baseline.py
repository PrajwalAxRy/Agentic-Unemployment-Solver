"""Regenerate the deterministic Phase 2 source-discovery baseline."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from job_finder.core.company_seed import load_company_seed
from job_finder.core.discovery_baseline import build_baseline_proposal


def main() -> int:
    """Write one provisional proposal for every canonical company."""
    repository_root = Path(__file__).resolve().parents[1]
    seed_path = repository_root / "data" / "company_seed.csv"
    output_path = repository_root / "data" / "source_discovery_proposals.json"
    records = load_company_seed(seed_path)
    payload = {
        "schema_version": 1,
        "batch_id": "canonical-seed-2026-09-20",
        "discovered_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "proposals": [build_baseline_proposal(record) for record in records],
    }
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(records)} proposals to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
