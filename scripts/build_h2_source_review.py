"""Generate the Phase 2 H2 source-review artifact from tracked proposals."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

from job_finder.core.source_discovery import SourceDiscoveryProposal, load_discovery_batch

ADAPTER_PRIORITY = (
    "ashby",
    "greenhouse",
    "lever",
    "workday",
    "darwinbox",
    "eightfold",
    "smartrecruiters",
    "oracle_cloud",
    "successfactors",
    "jobvite",
)

REPRESENTATIVES = {
    "ashby": "Deeptune (0), Kognitos (7), Kong (72), Cerebras Systems (113)",
    "greenhouse": "APT Portfolio (1), Glean (123), Motive (151), Qube Research (202)",
    "lever": "100ms (8), Doxel (13), Bazaarvoice (29)",
    "workday": "Fractal Analytics, CrowdStrike",
    "darwinbox": "Rapido, ClearTax, Porter, Unacademy",
    "eightfold": "NVIDIA, Millennium Management, PayPal",
}


def main() -> int:
    """Write the deterministic H2 Markdown review artifact."""
    root = Path(__file__).resolve().parents[1]
    batch = load_discovery_batch(root / "data" / "source_discovery_proposals.json")
    rows = sorted(batch.proposals, key=lambda item: item.source_rank)
    statuses = Counter(item.status.value for item in rows)
    adapters = Counter(item.adapter_type.value for item in rows)
    confidence = Counter(item.confidence.value for item in rows)
    by_adapter_status: dict[str, Counter[str]] = defaultdict(Counter)
    for item in rows:
        by_adapter_status[item.adapter_type.value][item.status.value] += 1
    reusable_total = sum(adapters[adapter] for adapter in ADAPTER_PRIORITY)

    output: list[str] = [
        "# H2 source inventory review",
        "",
        "## Checkpoint",
        "",
        "- Phase: 2 — Company source inventory",
        "- Checkpoint: H2 — approve sources and first-release scope",
        "- Status: **APPROVED — proceed instruction received 2026-09-20**",
        f"- Discovery batch: `{batch.batch_id}`",
        f"- Discovery timestamp: `{batch.discovered_at.isoformat()}`",
        "- Canonical scope: 330 of 330 companies; no company is removed or enabled",
        "",
        "## Decision summary",
        "",
        f"- Recommend accepting {statuses['auto_verified']} read-only verified sources as the "
        "source baseline, still disabled until their adapters pass later phase gates.",
        f"- Keep {statuses['access_concern']} access-concern sources disabled. Do not bypass "
        "login, CAPTCHA, rate-limit, robots, or other access controls.",
        f"- Keep {statuses['conflict']} conflicting or non-enumerating sources disabled in the "
        "custom-discovery backlog; none is proposed for removal.",
        f"- Carry {statuses['proposed']} responsive but oversized structured boards into adapter "
        "implementation with bounded streaming/pagination tests.",
        "- Recommend the adapter order: Ashby, Greenhouse, Lever, Workday, Darwinbox, "
        "Eightfold, SmartRecruiters, Oracle Cloud, SuccessFactors, then Jobvite.",
        "- Preserve all 330 companies in first-release accounting. Priority changes work order "
        "and reporting only, never inclusion.",
        "",
        "## Inventory accounting",
        "",
        "| Metric | Count | Percent of 330 |",
        "|---|---:|---:|",
    ]
    for label, count in (
        ("Read-only auto-verified", statuses["auto_verified"]),
        ("Access concern", statuses["access_concern"]),
        ("Conflict / non-enumerating", statuses["conflict"]),
        ("Responsive but oversized", statuses["proposed"]),
        ("High confidence", confidence["high"]),
        ("Medium confidence", confidence["medium"]),
        ("Low confidence", confidence["low"]),
    ):
        output.append(f"| {label} | {count} | {count / 330:.1%} |")

    output.extend(
        [
            "",
            "## Adapter coverage and priority",
            "",
            f"Known reusable ATS families cover {reusable_total} companies "
            f"({reusable_total / 330:.1%}). The remaining {adapters['search_only']} "
            "search-only records are an explicit custom/source-family backlog; "
            f"{adapters['unresolved']} conflicts have no usable adapter classification.",
            "",
            "| Priority | Adapter | Total | Verified | Access | Conflict | Pending | "
            "Projected registry coverage |",
            "|---:|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for index, adapter in enumerate(ADAPTER_PRIORITY, start=1):
        counts = by_adapter_status[adapter]
        total = adapters[adapter]
        output.append(
            f"| {index} | `{adapter}` | {total} | {counts['auto_verified']} | "
            f"{counts['access_concern']} | {counts['conflict']} | {counts['proposed']} | "
            f"{total / 330:.1%} |"
        )
    output.extend(
        [
            f"| backlog | `search_only` | {adapters['search_only']} | "
            f"{by_adapter_status['search_only']['auto_verified']} | "
            f"{by_adapter_status['search_only']['access_concern']} | "
            f"{by_adapter_status['search_only']['conflict']} | 0 | "
            f"{adapters['search_only'] / 330:.1%} |",
            f"| backlog | `unresolved` | {adapters['unresolved']} | 0 | 0 | "
            f"{by_adapter_status['unresolved']['conflict']} | 0 | "
            f"{adapters['unresolved'] / 330:.1%} |",
            "",
            "Ashby and Greenhouse have now passed full adapter-group validation for all 25 "
            "current mappings in each family. The next approved adapter family is Lever.",
            "",
            "### Representative boards",
            "",
        ]
    )
    for adapter, representatives in REPRESENTATIVES.items():
        output.append(f"- `{adapter}`: {representatives}")

    output.extend(
        [
            "",
            "## Unsupported or blocked proposals",
            "",
            "None are proposed as unsupported or removed at H2. Any access-concern or conflict "
            "companies remain in scope and disabled pending the approved disposition and later "
            "adapter-specific evidence.",
            "",
            "## Responsive but oversized structured boards",
            "",
        ]
    )
    output.extend(_table(item for item in rows if item.status.value == "proposed"))
    output.extend(
        [
            "",
            "## Access-policy concerns requiring approval",
            "",
            "Recommendation: keep disabled, do not bypass the observed control, and attempt only "
            "a documented public structured endpoint, custom public adapter, or native employer "
            "alert in later phases.",
            "",
        ]
    )
    output.extend(_table(item for item in rows if item.status.value == "access_concern"))
    output.extend(
        [
            "",
            "## Conflicting or non-enumerating proposals requiring inspection",
            "",
            "Recommendation: keep every company in scope but disabled; treat these as custom "
            "source-discovery work unless the listed evidence supports a correction.",
            "",
        ]
    )
    output.extend(_table(item for item in rows if item.status.value == "conflict"))
    output.extend(
        [
            "",
            "## Verified search-only sources requiring custom adapters or deeper family detection",
            "",
            "These official pages passed read-only checks but exposed no single supported hosted "
            "ATS fingerprint. They are recommended as the custom-adapter backlog, not as a claim "
            "that one generic scraper can safely cover all of them.",
            "",
        ]
    )
    output.extend(
        _table(
            item
            for item in rows
            if item.status.value == "auto_verified" and item.adapter_type.value == "search_only"
        )
    )
    output.extend(
        [
            "",
            "## Evidence and validation",
            "",
            "- Ranked search evidence exists for all 280 seed rows that originally contained "
            "only Google search hints.",
            "- Read-only probes used public URLs, a truthful client identifier, timeouts, bounded "
            "responses, and sanitized diagnostics; no credentials or page bodies are tracked.",
            "- Hosted-ATS fingerprints were applied only when one unambiguous supported "
            "configuration was present. Citi and Arm retained search-only classification because "
            "multiple public boards were detected.",
            "- The canonical registry reconciles 330/330 companies, contains zero enabled "
            "sources, and preserves all P1/P2/P3 priorities and source ranks.",
            "- Detailed proposal evidence: `data/source_discovery_proposals.json`.",
            "- Disabled runtime registry: `config/company_sources.json`.",
            "",
            "## Recorded decision",
            "",
            f"The approved package accepts the {statuses['auto_verified']} verified source "
            f"baselines; keeps the {statuses['access_concern']} access concerns, "
            f"{statuses['conflict']} conflicts, and {statuses['proposed']} oversized boards "
            "disabled without dropping any company; and uses the recommended adapter priority "
            "beginning with Ashby. The later access-concern recheck reduced observed access "
            "concerns without expanding permissions or enabling any source.",
        ]
    )
    output_path = root / "docs" / "reviews" / "h2_source_inventory_review.md"
    output_path.write_text("\n".join(output) + "\n", encoding="utf-8")
    print(f"Wrote H2 review artifact to {output_path}")
    return 0


def _table(items: Iterable[SourceDiscoveryProposal]) -> list[str]:
    rows = list(items)
    output = [
        "| Rank | Priority | Company | Adapter | Direct URL | Evidence / limitation |",
        "|---:|---|---|---|---|---|",
    ]
    for item in rows:
        if not isinstance(item, SourceDiscoveryProposal):
            raise TypeError("review table requires source proposals")
        url = item.official_careers_url or ""
        link = f"[open]({url})" if url else "none"
        reason = item.access_concern or item.notes or "See tracked proposal evidence."
        output.append(
            f"| {item.source_rank} | {item.priority} | {_escape(item.company_name)} | "
            f"`{item.adapter_type.value}` | {link} | {_escape(reason)} |"
        )
    if not rows:
        output.append("| — | — | None | — | — | — |")
    return output


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
