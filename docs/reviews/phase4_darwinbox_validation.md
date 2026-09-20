# Phase 4 Darwinbox adapter validation

## Result

- Status: **passed for all Darwinbox mappings**
- Generated at: `2026-09-20T19:37:00+05:30`
- Registry version: `0.1.0-provisional`
- Companies: 4
- Outcomes: `{"empty": 1, "success": 3}`
- Observed jobs: 141
- Fetched pages: 17
- Date evidence: `{"first_seen": 0, "published": 0, "unknown": 141, "updated": 0}`
- Missing required listing fields: 0
- Detail requests during full validation: 0

## Company results

| Rank | Priority | Company | Outcome | Jobs | Pages | Missing | Dates | Exceptions |
|---:|---|---|---|---:|---:|---:|---|---|
| 285 | P3 | Rapido | empty | 0 | 1 | 0 | none | none |
| 296 | P3 | ClearTax | success | 13 | 2 | 0 | unknown=13 | unverified_job_posting_on |
| 320 | P3 | Porter | success | 121 | 13 | 0 | unknown=121 | unverified_job_posting_on |
| 325 | P3 | Unacademy | success | 7 | 1 | 0 | unknown=7 | unverified_job_posting_on |

## Confirmed adapter behavior

- All four public career pages and candidate endpoints were reachable without authentication, CAPTCHA handling, browser cookies, or challenge solving.
- The API requires an ordinary same-origin careers-page `Referer`; the truthful job-finder user agent remains unchanged.
- Rapido returned a valid empty board. Porter exercised complete pagination with 121 jobs across 13 numbered pages before the four-company run.
- A Porter `Software Development Engineer III` detail check matched the listing ID, title, and location and returned a 9,242-character description.
- Its [public direct link](https://porter.darwinbox.in/ms/candidate/careers/a6979983a7016a) returned HTTP 200 without a redirect.

## Publication-date evidence

- All 141 non-empty listings expose epoch-valued `job_posting_on`, and sampled values align with `created_on`, but no public field contract was found that proves the timestamp is the publication instant.
- The values are retained with timezone-aware parsing but remain `unknown` date evidence for H5; no permanent include/exclude policy is selected here.

## Limitations

- Counts are point-in-time observations and will change as employers update boards.
- Full descriptions require the public per-job detail endpoint and are intentionally not fetched during lightweight listing validation.
- Sources remain disabled for normal scans until later pipeline phases are complete.
