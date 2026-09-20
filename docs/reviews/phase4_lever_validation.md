# Phase 4 Lever adapter validation

## Result

- Status: **passed for all current Lever mappings**
- Generated at: `2026-09-20T18:40:59+05:30`
- Registry version: `0.1.0-provisional`
- Companies: 11
- Outcomes: `{"success": 11}`
- Observed jobs: 386
- Jobs missing descriptions: 17
- Date evidence: `{"first_seen": 0, "published": 0, "unknown": 386, "updated": 0}`
- Pagination: `skip`/`limit` requests continue until a short page
- Official API contract: [Lever Postings API](https://github.com/lever/postings-api)

## Company results

| Rank | Priority | Company | Outcome | Jobs | Pages | Missing | Dates | Exceptions |
|---:|---|---|---|---:|---:|---:|---|---|
| 9 | P1 | Doxel | success | 13 | 1 | 0 | unknown=13 | unverified_created_at |
| 37 | P1 | Neuron7.ai | success | 18 | 1 | 0 | unknown=18 | unverified_created_at |
| 41 | P1 | Aera Technology | success | 14 | 1 | 0 | unknown=14 | unverified_created_at |
| 47 | P1 | Safe Security | success | 20 | 1 | 0 | unknown=20 | unverified_created_at |
| 70 | P1 | Level AI | success | 19 | 1 | 0 | unknown=19 | unverified_created_at |
| 97 | P2 | Bazaarvoice | success | 29 | 1 | 0 | unknown=29 | unverified_created_at |
| 124 | P2 | 100ms | success | 8 | 1 | 0 | unknown=8 | unverified_created_at |
| 133 | P2 | BarRaiser | success | 18 | 1 | 16 | unknown=18 | unverified_created_at, missing_description |
| 142 | P2 | Dozee | success | 25 | 1 | 0 | unknown=25 | unverified_created_at |
| 178 | P2 | RapidAI | success | 17 | 1 | 0 | unknown=17 | unverified_created_at |
| 317 | P3 | Paytm | success | 205 | 3 | 1 | unknown=205 | unverified_created_at, missing_description |

## Corrections and manual evidence

- Bazaarvoice exposed one job with an empty plain-text description but populated HTML. A saved regression fixture now verifies the HTML fallback.
- Lever sometimes stores requirements only in structured `lists`; those fields are now included so AI duties and experience requirements are not lost.
- BarRaiser exposes 16 jobs and Paytm one job with no description in either the list or single-posting public API. The jobs remain visible with `missing_description` evidence for later manual-review handling.
- Dream Sports' official careers page still links to the obsolete `dreamsports` Lever board, but both the board and API return HTTP 404. It remains in the approved 330-company scope as a documented search-only conflict, not a verified Lever source.

## Publication-date evidence

- All observed Lever jobs expose `createdAt`, but the public Postings API documentation does not define it as publication time.
- All 386 jobs therefore remain `unknown` date evidence for the mandatory H5 coverage review; no permanent include/exclude policy is selected here.

## Limitations

- Counts are point-in-time observations and will change as employers update boards.
- A missing description prevents automatic AI-work and seniority assessment; those jobs must remain explicit rather than being silently rejected.
- Sources remain disabled for normal scans until later pipeline phases are complete.
