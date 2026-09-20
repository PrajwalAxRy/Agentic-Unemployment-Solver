# Phase 4 Greenhouse adapter validation

## Result

- Status: **passed**
- Generated at: `2026-09-20T18:16:49+05:30`
- Registry version: `0.1.0-provisional`
- Companies: 25
- Outcomes: `{"success": 25}`
- Observed jobs: 2268
- Missing required fields: 0
- Date evidence: `{"first_seen": 0, "published": 2265, "unknown": 0, "updated": 3}`
- Pagination: one complete public `jobs` collection checked against `meta.total`
- Official API contract: [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html)

## Company results

| Rank | Priority | Company | Outcome | Jobs | Pages | Missing | Dates | Exceptions |
|---:|---|---|---|---:|---:|---:|---|---|
| 1 | P1 | Glean | success | 123 | 1 | 0 | published=123 | none |
| 26 | P1 | Jumio | success | 27 | 1 | 0 | published=27 | none |
| 27 | P1 | Motive | success | 151 | 1 | 0 | published=151 | none |
| 28 | P1 | Observe.AI | success | 15 | 1 | 0 | published=15 | none |
| 32 | P1 | Pure Storage | success | 354 | 1 | 0 | published=354 | none |
| 33 | P1 | Atomicwork | success | 27 | 1 | 0 | published=27 | none |
| 43 | P1 | Enterpret | success | 15 | 1 | 0 | published=15 | none |
| 45 | P1 | Prodigal | success | 13 | 1 | 0 | published=13 | none |
| 68 | P1 | Databricks | success | 877 | 1 | 0 | published=877 | none |
| 77 | P1 | Razorpay | success | 18 | 1 | 0 | published=18 | none |
| 81 | P1 | AlphaGrep | success | 15 | 1 | 0 | published=14, updated=1 | updated_date_fallback |
| 82 | P1 | APT Portfolio | success | 1 | 1 | 0 | published=1 | none |
| 84 | P1 | Graviton Research Capital | success | 19 | 1 | 0 | published=18, updated=1 | updated_date_fallback |
| 89 | P1 | Quantbox Research | success | 8 | 1 | 0 | published=8 | none |
| 90 | P1 | Qube Research & Technologies | success | 202 | 1 | 0 | published=202 | none |
| 104 | P2 | Together AI | success | 78 | 1 | 0 | published=78 | none |
| 106 | P2 | EnCharge AI | success | 26 | 1 | 0 | published=26 | none |
| 127 | P2 | AiDash | success | 8 | 1 | 0 | published=8 | none |
| 130 | P2 | Arcana Analytics | success | 28 | 1 | 0 | published=28 | none |
| 143 | P2 | Dscout | success | 9 | 1 | 0 | published=9 | none |
| 144 | P2 | EarnIn | success | 17 | 1 | 0 | published=17 | none |
| 201 | P2 | Zeta Global | success | 145 | 1 | 0 | published=145 | none |
| 235 | P3 | Endor Labs | success | 26 | 1 | 0 | published=26 | none |
| 248 | P3 | SingleStore | success | 40 | 1 | 0 | published=39, updated=1 | updated_date_fallback |
| 283 | P3 | Netradyne | success | 26 | 1 | 0 | published=26 | none |

## Corrections and manual evidence

- Databricks and Graviton Research Capital embedded URLs had been misparsed as board token `embed`; their public tokens are `databricks` and `gravitonresearchcapital`.
- Clipboard Health's official careers page now links to the public Ashby board `clipboard`; the obsolete Greenhouse board returns HTTP 404. Clipboard was moved to the Ashby cohort and that entire cohort was revalidated.
- Databricks returned 877 jobs in a 9.6 MB response. The shared client remains bounded, with a tested 20 MB maximum that safely covers the observed board.
- Pure Storage returned 354 complete jobs, resolving its earlier two-megabyte discovery-probe limitation.

## Publication-date evidence

- Greenhouse `first_published` is retained as publication evidence.
- AlphaGrep, Graviton Research Capital, and SingleStore each had one job without `first_published`; those three jobs retain `updated_at` with an explicit `updated_date_fallback` diagnostic.
- No permanent inclusion/exclusion decision is made here. The fallback jobs remain separate for the mandatory full-registry H5 date-coverage review.

## Limitations

- Counts are point-in-time observations and will change as employers update boards.
- Completeness is based on the official public API's collection and `meta.total`; client-rendered board DOM counts are not used.
- Sources remain disabled for normal scans until later pipeline phases are complete.
