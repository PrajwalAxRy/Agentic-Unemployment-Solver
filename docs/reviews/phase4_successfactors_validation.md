# Phase 4 SuccessFactors validation

## Result

Status: **passed for the current SuccessFactors mapping**

The SAP India public SuccessFactors Recruiting Marketing category passed full adapter-group
validation on 2026-09-21. Requests used the bounded shared HTTP client with a truthful client
identity and same-origin public careers-page referers. No authentication, cookies, browser
session, CAPTCHA bypass, or access-control workaround was used.

| Company | Jobs | Pages | Missing required fields | Listing-date evidence |
|---|---:|---:|---:|---|
| SAP | 46 | 2 | 0 | 46 unknown until detail retrieval |

The category page reported `Results 1–25 of 46` and `Results 26–46 of 46`. The adapter checks
each returned range against the requested offset, rejects duplicate identities and repeated pages,
and requires the final range to reach the reported total. Total changes remain visible because a
public inventory can change during a multi-page scan.

## Identity, date, and detail evidence

Public job links end with a stable numeric SuccessFactors RMK posting ID, which supplies listing
identity and the direct canonical URL. The listing table exposes title and India location but no
publication date. Jobs therefore remain explicitly `unknown` at listing time.

The sampled public detail for posting `1280449101` matched the listing identity and URL. It exposed
`datePosted="Sat Aug 29 02:00:00 UTC 2026"` in schema.org `JobPosting` metadata and the same date as
the visible `Posted Date`; the adapter marks that detail value `published`. The detail supplied a
9,843-character normalized description whose hash was generated without retaining the live text in
this tracked artifact.

## Moody's source-family correction

Moody's official public inventory is hosted by Radancy at
`https://careers.moodys.com/en/search-jobs`. The SuccessFactors URL found in its page is only the
`Returning applicants` login route and does not enumerate jobs. Moody's is therefore no longer
mapped to this adapter; it remains disabled and visible in the H2-approved custom-discovery backlog
as `search_only`.

This correction does not trigger H4: Moody's is a P3 company, no source or access control is being
bypassed, and H2 already approved carrying corrected non-enumerating sources in the disabled custom
backlog. No company was removed from the 330-company accounting.

The complete sanitized runtime report is `reports/successfactors_full_verification.json`; it is
ignored by Git. H3 was not triggered because the SAP listing, pagination, direct links, and detail
page were verified with available read-only tools.
