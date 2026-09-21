# Phase 4 Oracle Cloud validation

## Result

Status: **passed for both Oracle Cloud mappings**

The public Oracle Recruiting Candidate Experience resources passed full adapter-group validation
on 2026-09-21. Requests used the bounded shared HTTP client with a truthful client identity and
same-origin public careers-page referers. No authentication, cookies, browser session, CAPTCHA
bypass, or access-control workaround was used.

| Company | Jobs | Pages | Missing required fields | Date evidence |
|---|---:|---:|---:|---|
| Uber | 532 | 3 | 0 | 532 `PostedDate` published |
| JPMorganChase | 7,355 | 37 | 0 | 7,355 `PostedDate` published |

Oracle's REST documentation defines `PostedDate` as the date of posting of the requisition list.
The adapter therefore preserves the date-only value and marks it `published`. The stable `Id`
field supplies job identity, and direct public routes use `/job/<Id>`.

## Pagination evidence

The API returns one search envelope with `TotalJobsCount`, `Limit`, `Offset`, and
`requisitionList`. The large JPMorganChase board demonstrated two live behaviors that now have
regression coverage:

- The inventory total can change during a long scan. Total drift remains visible as a warning,
  while the collector continues through the latest reported offset range.
- A nonterminal offset range can contain fewer than the requested 200 items. Direct probes showed
  that the next correct offset is still the prior offset plus the requested limit; advancing by
  the returned count creates overlaps.

Duplicate IDs, repeated pages, empty intermediate ranges, offset mismatches, malformed jobs, and
page-limit exhaustion remain suspicious or failed outcomes rather than healthy completion.

## Detail evidence

One public detail response from each company matched the listing ID and canonical URL and supplied
a readable full description. The sampled Uber detail contained 4,176 normalized characters; the
sampled JPMorganChase detail contained 2,376. Description hashes were generated without retaining
the live text in the tracked review artifact.

The complete sanitized runtime report is `reports/oracle_cloud_full_verification.json`; it is
ignored by Git. H3 and H4 were not triggered because both public boards, direct links, pagination,
date meaning, and detail retrieval were verified with available read-only tools.
