"""Fingerprint hosted ATS links on verified search-only career pages."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from job_finder.core.source_discovery import load_discovery_batch
from job_finder.core.source_fingerprint import fingerprint_public_page


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--limit", type=int, default=None)
    return parser


def main() -> int:
    """Run sequential bounded probes and retain only sanitized fingerprints."""
    args = build_parser().parse_args()
    root = Path(__file__).resolve().parents[1]
    batch = load_discovery_batch(root / "data" / "source_discovery_proposals.json")
    proposals = [
        proposal
        for proposal in batch.proposals
        if proposal.status.value == "auto_verified"
        and proposal.adapter_type.value == "search_only"
        and proposal.official_careers_url is not None
    ]
    if args.limit is not None:
        proposals = proposals[: args.limit]
    results = []
    for index, proposal in enumerate(proposals, start=1):
        assert proposal.official_careers_url is not None
        result = fingerprint_public_page(
            proposal.company_id,
            proposal.official_careers_url,
            timeout_seconds=args.timeout,
        )
        results.append(result.as_json())
        print(f"[{index}/{len(proposals)}] {proposal.company_name}: {result.outcome}")
    output_path = root / "diagnostics" / "source_fingerprints.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "fingerprinted_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "result_count": len(results),
                "results": results,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote sanitized fingerprints to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
