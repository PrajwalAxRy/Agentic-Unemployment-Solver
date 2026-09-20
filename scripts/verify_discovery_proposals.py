"""Run bounded public probes for direct Phase 2 source proposals."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from job_finder.core.source_discovery import DiscoveryStatus, load_discovery_batch
from job_finder.core.source_probe import probe_public_url


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=12.0)
    return parser


def main() -> int:
    """Probe provisional public URLs and write only sanitized metadata."""
    args = build_parser().parse_args()
    repository_root = Path(__file__).resolve().parents[1]
    input_path = repository_root / "data" / "source_discovery_proposals.json"
    output_path = repository_root / "diagnostics" / "source_discovery_verification.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    batch = load_discovery_batch(input_path)
    proposals = [
        proposal for proposal in batch.proposals if proposal.status is DiscoveryStatus.PROPOSED
    ]
    if args.limit is not None:
        proposals = proposals[: args.limit]

    results: list[dict[str, object]] = []
    for index, proposal in enumerate(proposals, start=1):
        probes = []
        if proposal.official_careers_url is not None:
            probes.append(
                probe_public_url(
                    proposal.official_careers_url,
                    expect_json_jobs=False,
                    timeout_seconds=args.timeout,
                ).as_json()
            )
        if (
            proposal.list_endpoint is not None
            and proposal.list_endpoint != proposal.official_careers_url
        ):
            probes.append(
                probe_public_url(
                    proposal.list_endpoint,
                    expect_json_jobs=proposal.adapter_type.value
                    in {"greenhouse", "ashby", "lever"},
                    timeout_seconds=args.timeout,
                ).as_json()
            )
        results.append(
            {
                "company_id": proposal.company_id,
                "company_name": proposal.company_name,
                "adapter_type": proposal.adapter_type.value,
                "probes": probes,
            }
        )
        print(f"[{index}/{len(proposals)}] {proposal.company_name}")

    payload = {
        "schema_version": 1,
        "proposal_batch_id": batch.batch_id,
        "verified_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "result_count": len(results),
        "results": results,
    }
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote sanitized verification to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
