"""Build a disabled provisional registry from the complete discovery batch."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from job_finder.core.source_discovery import (
    load_discovery_batch,
    proposal_to_disabled_source,
)


def main() -> int:
    """Write deterministic Phase 2 registry content; never enable a proposal."""
    repository_root = Path(__file__).resolve().parents[1]
    proposal_path = repository_root / "data" / "source_discovery_proposals.json"
    output_path = repository_root / "config" / "company_sources.json"
    batch = load_discovery_batch(proposal_path)
    sources: list[dict[str, Any]] = []
    for proposal in sorted(batch.proposals, key=lambda item: item.source_rank):
        source = proposal_to_disabled_source(proposal)
        item = asdict(source)
        item["status"] = source.status.value
        item["adapter_type"] = source.adapter_type.value
        item["identity_strategy"] = source.identity_strategy.value
        item["date_strategy"]["basis"] = source.date_strategy.basis.value
        item["detail_strategy"] = source.detail_strategy.value
        item["confidence"] = source.confidence.value
        item["source_rank"] = proposal.source_rank
        item["priority"] = proposal.priority
        item["last_verified_at"] = (
            batch.discovered_at.isoformat() if proposal.status.value == "auto_verified" else None
        )
        sources.append(item)
    payload = {
        "schema_version": 1,
        "registry_version": "0.1.0-provisional",
        "generated_at": batch.discovered_at.isoformat(),
        "discovery_batch_id": batch.batch_id,
        "sources": sources,
    }
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(sources)} disabled company sources to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
