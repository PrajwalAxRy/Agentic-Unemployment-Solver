"""Validate and summarize the full company-source registry."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from job_finder.core.company_registry import audit_company_registry, load_company_registry
from job_finder.core.company_seed import load_company_seed


def main() -> int:
    """Print a stable full-seed audit and fail when reconciliation is incomplete."""
    repository_root = Path(__file__).resolve().parents[1]
    registry = load_company_registry(repository_root / "config" / "company_sources.json")
    seed = load_company_seed(repository_root / "data" / "company_seed.csv")
    audit = audit_company_registry(registry, seed)
    print(json.dumps(asdict(audit), indent=2, sort_keys=True))
    return 0 if audit.reconciled else 1


if __name__ == "__main__":
    raise SystemExit(main())
