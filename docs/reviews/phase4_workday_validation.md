# Phase 4 Workday adapter validation

## Result

- Status: **passed for all Workday mappings**
- Generated at: `2026-09-20T19:17:51+05:30`
- Registry version: `0.1.0-provisional`
- Companies: 13
- Outcomes: `{"success": 13}`
- Observed jobs: 9198
- Fetched pages: 467
- Listings missing source locations: 3
- Date evidence: `{"first_seen": 0, "published": 0, "unknown": 9198, "updated": 0}`
- Detail requests during full validation: 0

## Company results

| Rank | Priority | Company | Outcome | Jobs | Pages | Missing | Dates | Exceptions |
|---:|---|---|---|---:|---:|---:|---|---|
| 38 | P1 | Uniphore | success | 37 | 2 | 0 | unknown=37 | relative_posted_on |
| 64 | P1 | CrowdStrike | success | 371 | 19 | 0 | unknown=371 | relative_posted_on |
| 98 | P2 | Fractal Analytics | success | 137 | 7 | 1 | unknown=137 | relative_posted_on, missing_location |
| 204 | P3 | Bank of America | success | 2023 | 102 | 0 | unknown=2023 | relative_posted_on |
| 205 | P3 | Barclays | success | 874 | 44 | 1 | unknown=874 | relative_posted_on, missing_location |
| 213 | P3 | London Stock Exchange Group | success | 722 | 37 | 0 | unknown=722 | relative_posted_on |
| 217 | P3 | Nasdaq | success | 183 | 10 | 0 | unknown=183 | relative_posted_on |
| 221 | P3 | Visa | success | 794 | 40 | 0 | unknown=794 | relative_posted_on |
| 244 | P3 | Palo Alto Networks | success | 1510 | 76 | 0 | unknown=1510 | relative_posted_on |
| 254 | P3 | Workday | success | 365 | 19 | 0 | unknown=365 | relative_posted_on |
| 256 | P3 | Analog Devices | success | 785 | 40 | 0 | unknown=785 | relative_posted_on |
| 259 | P3 | Cadence | success | 608 | 31 | 1 | unknown=608 | relative_posted_on, missing_location |
| 265 | P3 | NXP Semiconductors | success | 789 | 40 | 0 | unknown=789 | relative_posted_on |

## Confirmed adapter behavior

- A bounded first-page probe succeeded for all 13 configured hosts without login, CAPTCHA, or access-control handling.
- Workday returns the authoritative result total on offset 0 and reports total 0 on later pages. A saved regression covers this behavior; completeness is measured against the first-page total.
- Representative complete scans covered CrowdStrike (371 jobs / 19 pages), Fractal Analytics (137 / 7), and London Stock Exchange Group (722 / 37) before the full run.
- A CrowdStrike detail check matched the list title and requisition ID, exposed its primary and additional locations, returned a full description, and produced a direct public job URL.
- Representative direct links returned HTTP 200 without authentication: [CrowdStrike](https://crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers/job/USA---Sunnyvale-CA/Sr-Engineer---EPP--Windows-Sensor--Hybrid-_R30087), [Fractal](https://fractal.wd1.myworkdayjobs.com/Careers/job/Automation-Test-Engineer_SR-20170), [Barclays](https://barclays.wd3.myworkdayjobs.com/External_Career_Site_Barclays/job/XMLNAME-2027-Technology-Developer-Graduate-Program-Whippany_JR-0000123244), and [Cadence](https://cadence.wd1.myworkdayjobs.com/External_Careers/job/Principal-Design-Engineer_R49256).

## Missing-location evidence

- One listing each at Fractal Analytics, Barclays, and Cadence lacked location in both the list and detail payloads. All three still had valid descriptions and direct links, so they remain visible as `Location unavailable` rather than being discarded.
- The affected observations were Fractal `Automation Test Engineer` (`SR-20170`), Barclays `2027 Technology Developer Graduate Program Whippany` (`JR-0000123244`), and Cadence `Principal Design Engineer` (`R49256`).

## Publication-date evidence

- All 9,198 listings exposed relative `postedOn` labels such as `Posted Today`, `Posted 9 Days Ago`, and `Posted 30+ Days Ago`; none was promoted to a reliable publication timestamp.
- Detail payloads expose `startDate`, but live checks showed it can be years old for an active posting. It is retained only as metadata and is not treated as publication time.
- Every Workday listing therefore remains `unknown` date evidence for H5; no permanent include/exclude policy is selected here.

## Limitations

- Counts are point-in-time observations and will change as employers update boards.
- Some list payloads collapse multiple locations to labels such as `2 Locations`; the public detail endpoint is required before deterministic location filtering.
- Sources remain disabled for normal scans until later pipeline phases are complete.
