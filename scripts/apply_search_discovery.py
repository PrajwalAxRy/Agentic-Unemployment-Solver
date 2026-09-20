"""Apply credible ranked-search results to unresolved discovery proposals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from job_finder.core.search_discovery import (
    apply_search_selections,
    load_search_candidate_batch,
    select_credible_sources,
)


def _load_json(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as stream:
        raw: Any = json.load(stream)
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return raw


def main() -> int:
    """Update proposals in place while leaving weak search results unresolved."""
    root = Path(__file__).resolve().parents[1]
    candidate_paths = (
        ("isolated retry", root / "data" / "source_search_isolated_retries.json"),
        ("batch retry", root / "data" / "source_search_retries.json"),
        ("initial search", root / "data" / "source_search_candidates.json"),
    )
    selections = select_credible_sources(
        (name, load_search_candidate_batch(path)) for name, path in candidate_paths
    )
    proposal_path = root / "data" / "source_discovery_proposals.json"
    revised = apply_search_selections(_load_json(proposal_path), selections)
    proposal_path.write_text(
        json.dumps(revised, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Applied {len(selections)} credible search proposals to {proposal_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
