# Phase 1 canonical company schema audit

**Run date:** 2026-09-20

**Input:** `data/company_seed.csv`

**Command:** `uv run --locked python scripts/audit_company_seed.py`

## Result

| Metric | Count |
|---|---:|
| Total companies | 330 |
| Unique company IDs | 330 |
| Unique company names | 330 |
| Unique source ranks | 330 |
| P1 companies | 96 |
| P2 companies | 106 |
| P3 companies | 128 |
| Duplicate IDs | 0 |
| Duplicate names | 0 |
| Duplicate source ranks | 0 |
| Invalid minimum source configurations | 0 |
| Missing verified official URLs | 330 |
| Missing verified adapter types | 330 |

The 330 missing official URLs and adapter types are expected Phase 1 gaps, not omissions. Each seed
row successfully loads as one disabled `unresolved` company-source record. The original
`careers_url_hint` is retained only as unverified discovery evidence. Phase 2 must verify official
sources and adapter parameters before any company is enabled.

## Approved search profile

- Profile ID: `india-ai-ml-under-five-years`
- Profile version: `1.0.0`
- Schema version: `1`
- Content hash: `e69047cc5529ea4e6aeef4c05c13bfa5e8cff2892889c83a1e698f5d677abc22`
- Role examples: 14
- Location examples: 15
- Seniority examples: 20
- Date uncertainty: `measure_then_decide`, pending mandatory H5 decision

## Gate conclusion

Phase 1 passes: every canonical company is accounted for, product decisions are versioned rather
than hard-coded, labelled examples are machine-readable, and source-specific behavior remains
unresolved until the source inventory phase.
