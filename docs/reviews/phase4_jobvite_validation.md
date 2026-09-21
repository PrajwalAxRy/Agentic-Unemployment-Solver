# Phase 4 Jobvite validation

## Result

Status: **passed for the Jobvite mapping**

The SiMa.ai public Jobvite board passed full adapter-group validation on 2026-09-21. Requests used
the bounded shared HTTP client with a truthful client identity and the official employer careers
page as referer. No authentication, cookies, browser session, CAPTCHA bypass, or access-control
workaround was used.

| Company | Jobs | Pages | Missing required fields | Listing-date evidence |
|---|---:|---:|---:|---|
| SiMa.ai | 18 | 1 | 0 | 18 unknown until detail retrieval |

## Completeness evidence

The standard public Jobvite desktop board at `https://jobs.jobvite.com/simaai/jobs?nl=1` rendered
one `Open Positions` view containing 18 unique job links and no pagination control. The `nl=1`
parameter is part of Jobvite's own public embed and redirect flow; it selects the Jobvite-rendered
desktop content instead of redirecting back to the employer wrapper page.

The adapter requires the Jobvite jobs-page markers, rejects missing title, location, or link data,
and treats duplicate identities as suspicious. If Jobvite adds a next-page or pagination control,
the adapter stops as suspicious instead of silently claiming that the first page is complete.

## Identity, date, and detail evidence

Each public link contains a stable Jobvite job ID, which supplies listing identity and a direct
canonical URL. The listing page exposes title and location but no publication date, so all 18 jobs
remain explicitly `unknown` until detail retrieval.

The sampled Bengaluru detail for Jobvite ID `oCzUzfwo` matched the listing identity and URL. Its
schema.org `JobPosting` JSON-LD exposed `datePosted="2026-03-31"`, a structured location, and a
1,705-character normalized description. The adapter marks the parsed date `published` and hashes
the description without retaining the live text in this tracked artifact.

The complete sanitized runtime report is `reports/jobvite_full_verification.json`; it is ignored by
Git. H3 and H4 were not triggered because the public list, completeness behavior, stable links,
and detail resource were verified with available read-only tools.
