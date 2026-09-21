# Phase 4 adapter coverage completion

## Result

Status: **passed**

Phase 4 completed on 2026-09-21 after a fresh listing-only verification of every enabled source.
The run used registry version `0.2.0-phase4`, the bounded shared HTTP client, and public resources
only. It did not retrieve detail pages, call an LLM, authenticate, or bypass an access control.

The complete sanitized runtime report is
`reports/phase4_full_registry_verification.json`; it is ignored by Git. This tracked artifact
records the completion evidence without retaining live response bodies.

## Registry reconciliation

| Category | Companies | Disposition |
|---|---:|---|
| Canonical seed | 330 | All companies remain in first-release accounting |
| Enabled reusable adapters | 86 | 84 successful sources and 2 valid empty sources |
| Search-only backlog | 238 | Disabled with official-source or conflict evidence retained |
| Unresolved backlog | 4 | Disabled pending source discovery |
| Unsupported | 2 | NVIDIA and PayPal; H4-approved official-page manual fallbacks |

The registry has 86 enabled and 244 disabled records. The status totals are 86 `enabled`, 242
`proposed`, and 2 `unsupported`; the 242 proposed records consist of 238 `search_only` and 4
`unresolved` adapter types. These categories reconcile all 330 canonical companies.

## Full enabled-registry result

- Outcomes: `{"empty": 2, "success": 84}`
- Observed jobs: 26,107
- Fetched pages: 661
- Failed, blocked, partial, or suspicious companies: 0
- Missing-field occurrences: 20
- Date evidence: `{"first_seen": 0, "published": 16142, "unknown": 9962, "updated": 3}`

| Adapter | Companies | Jobs | Pages | Success | Valid empty | Published | Updated | Unknown |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Ashby | 25 | 1,027 | 25 | 24 | 1 | 1,027 | 0 | 0 |
| Darwinbox | 4 | 141 | 17 | 3 | 1 | 0 | 0 | 141 |
| Eightfold | 1 | 224 | 23 | 1 | 0 | 0 | 0 | 224 |
| Greenhouse | 25 | 2,269 | 25 | 25 | 0 | 2,266 | 3 | 0 |
| Jobvite | 1 | 18 | 1 | 1 | 0 | 0 | 0 | 18 |
| Lever | 11 | 374 | 13 | 11 | 0 | 0 | 0 | 374 |
| Oracle Cloud | 2 | 7,897 | 40 | 2 | 0 | 7,897 | 0 | 0 |
| SmartRecruiters | 3 | 4,952 | 52 | 3 | 0 | 4,952 | 0 | 0 |
| SuccessFactors | 1 | 47 | 2 | 1 | 0 | 0 | 0 | 47 |
| Workday | 13 | 9,158 | 463 | 13 | 0 | 0 | 0 | 9,158 |

## Reviewed exceptions

The 20 missing-field occurrences remain visible and do not make the listing scans incomplete:

- BarRaiser has 16 jobs without descriptions in the public payload.
- Paytm has one job without a description.
- Fractal Analytics, Barclays, and Cadence each have one job without a location. The adapters
  retain those listings with `Location unavailable` instead of silently dropping them.

Barclays and Visa each exposed an identifier-only Workday placeholder row. The adapter counts the
row for pagination but does not emit it as a usable job. Bosch changed its active inventory total
during the scan. Regression coverage now preserves these conditions as explicit warnings while
still checking offsets, duplicate identities, repeated pages, malformed records, and short pages.
JPMorganChase returned a short nonterminal Oracle Cloud page, which is an already-covered healthy
active-inventory behavior.

The date totals are evidence for Phase 5, not an uncertain-date policy decision. In particular,
Workday, Lever, Darwinbox, Eightfold, Jobvite listings, and SuccessFactors listings retain their
documented uncertainty, and the three Greenhouse update-date fallbacks remain `updated`. No value
was promoted to a reliable publication date without source evidence.

## Gate decision

The enabled-company categories reconcile 86 of 86, the full live verifier returned success, no
shared request or pagination defect remains open, and the two important unsupported sources have
the H4-approved disposition and fallback. Phase 4 is complete. Phase 5 may proceed with shared
normalization and registry-wide recency measurement; H5 remains mandatory before any uncertain-date
treatment is selected.
