# Company seed data

`company_seed.csv` is the canonical first-release company list used by the job-finder build.

## Scope

- 330 companies.
- All workbook priority groups are included: 96 P1, 106 P2, and 128 P3.
- The source order is retained in `source_rank`.
- Company names, generated IDs, and source ranks are unique in this snapshot.

## Provenance

- Source workbook: `outputs/india_ai_ml_targets_2026_09_20/India_AI_ML_High_Paying_Companies_2026.xlsx`
- Source worksheet: `Targets`
- Header row: 8
- Source data rows: 9–338
- Source range: `A8:O338`
- Source SHA-256: `36877d813316f91b0f4b826eebee4d04530e11f70370fdff54d48755f94902a5`
- Extracted on: 20 September 2026

The workbook is provenance material and must remain unchanged. It is not a runtime dependency once the seed has been imported.

## Columns

| Column | Meaning |
|---|---|
| `company_id` | Deterministic lowercase slug generated from the source company name |
| `company_name` | Company name from the workbook |
| `priority` | Workbook priority: P1, P2, or P3; retained for reporting, not first-release exclusion |
| `careers_url_hint` | Workbook careers, board, search, or example-role URL used only as source-discovery evidence |
| `source_rank` | Original workbook rank used to preserve source ordering and reconcile rows |

`careers_url_hint` is not an approved official source. Phase 2 must verify the official careers source, adapter family, parameters, date behavior, job identity, and access status before enabling a company.

## Identity generation

The initial `company_id` values were generated deterministically from `company_name` by:

1. Applying Unicode NFKD normalization and removing combining marks.
2. Replacing `&` with `and` and `+` with `plus`.
3. Converting to lowercase.
4. Replacing remaining non-alphanumeric runs with a single hyphen.
5. Trimming leading and trailing hyphens.
6. Rejecting the export if two companies produce the same ID.

Do not regenerate IDs casually after the system begins storing job history. A source-name correction must preserve the existing ID or use an explicit migration.
