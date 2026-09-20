"""Apply deterministic source migrations found during adapter validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from job_finder.core.adapter_mapping_corrections import (
    apply_adapter_mapping_corrections,
    load_adapter_mapping_corrections,
)


def _load(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as stream:
        payload: Any = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    proposal_path = root / "data" / "source_discovery_proposals.json"
    corrections = load_adapter_mapping_corrections(
        root / "data" / "adapter_mapping_corrections.json"
    )
    revised = apply_adapter_mapping_corrections(_load(proposal_path), corrections)
    proposal_path.write_text(
        json.dumps(revised, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Applied adapter mapping corrections to {proposal_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
