"""Full canonical-seed and minimum source-schema validation."""

from pathlib import Path

from job_finder.core.company_seed import (
    build_minimum_source_audit,
    load_company_seed,
    minimum_company_source,
)
from job_finder.core.source_contracts import AdapterType, SourceStatus


def test_canonical_company_seed_has_all_330_unique_companies() -> None:
    records = load_company_seed(Path("data/company_seed.csv"))

    assert len(records) == 330
    assert len({record.company_id for record in records}) == 330
    assert len({record.company_name for record in records}) == 330
    assert len({record.source_rank for record in records}) == 330
    assert records[0].company_id == "glean"
    assert records[-1].company_id == "zoho"


def test_canonical_seed_priority_counts_match_provenance() -> None:
    audit = build_minimum_source_audit(load_company_seed(Path("data/company_seed.csv")))

    assert audit.priority_counts == {"P1": 96, "P2": 106, "P3": 128}


def test_every_seed_row_loads_as_explicit_unresolved_source() -> None:
    records = load_company_seed(Path("data/company_seed.csv"))
    sources = tuple(minimum_company_source(record) for record in records)

    assert len(sources) == 330
    assert all(source.status is SourceStatus.UNRESOLVED for source in sources)
    assert all(source.adapter_type is AdapterType.UNRESOLVED for source in sources)
    assert all(source.enabled is False for source in sources)
    assert all(source.careers_url is None for source in sources)


def test_phase_one_minimum_source_audit_reconciles() -> None:
    audit = build_minimum_source_audit(load_company_seed(Path("data/company_seed.csv")))

    assert audit.total_companies == 330
    assert audit.unique_company_ids == 330
    assert audit.unique_company_names == 330
    assert audit.unique_source_ranks == 330
    assert audit.missing_official_urls == 330
    assert audit.missing_adapter_types == 330
    assert audit.invalid_configuration == 0
