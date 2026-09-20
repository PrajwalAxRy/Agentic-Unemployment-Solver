"""Print the Phase 1 minimum company-source accounting report."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from job_finder.core.company_seed import build_minimum_source_audit, load_company_seed


def main() -> int:
    """Load all seed companies and print their minimum-schema audit as JSON."""
    repository_root = Path(__file__).resolve().parents[1]
    records = load_company_seed(repository_root / "data" / "company_seed.csv")
    audit = build_minimum_source_audit(records)
    print(json.dumps(asdict(audit), indent=2, sort_keys=True))
    return 0 if audit.invalid_configuration == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
