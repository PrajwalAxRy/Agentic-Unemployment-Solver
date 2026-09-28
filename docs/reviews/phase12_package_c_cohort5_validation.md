# Phase 12 Package C cohort 5 validation

**Status: complete — 4 official deterministic sources activated; 1 candidate failed closed.**

The user approved Packages A, B, and C on 2026-09-28. This fifth Package C cohort assessed the
next five P1 candidates: Atlassian, GitLab, LinkedIn, Qure.ai, and Airbnb. Atlassian, GitLab,
Qure.ai, and Airbnb passed their activation gates. LinkedIn remains disabled and `search_only`.
Packages D and E remain unapproved.

## Browser discovery and route selection

Discovery used locally installed Playwright Chromium because Windows browser control was not
available. Each official careers surface was rendered and visually inspected, representative job
links were clicked, and listing/detail screenshots were inspected locally. The screenshots and
network probes were temporary diagnostics and were not committed. Every selected request was then
replayed without cookies or browser state. No authentication, CAPTCHA, rate limit, robots control,
or other access restriction was bypassed.

| Company | Browser and public-request evidence | Decision |
|---|---|---|
| Atlassian | The official all-jobs page rendered 285 distinct roles and called the same-origin `/endpoint/careers/listings` collection. The response contained 300 portal rows representing 285 stable job IDs. | Activate `atlassian_careers_inventory`; collapse only consistent portal variants. |
| GitLab | The official careers page linked to its public Greenhouse board and the `gitlab` board API returned complete content-bearing jobs. | Activate the existing Greenhouse adapter with board token `gitlab`. |
| LinkedIn | The official careers search routed to LinkedIn's public company-jobs feed, which displayed only a partial recent set behind a sign-in overlay. | Fail closed; no complete bounded public inventory contract was proven. |
| Qure.ai | The official site linked to a branded Zoho careers page. Its raw HTML embedded the same 14-row collection rendered by the browser, including full descriptions and stable numeric IDs. | Activate `qure_zoho_embedded`; retain `Date_Opened` as unknown date evidence. |
| Airbnb | The official positions page exposed server-rendered rows and a public FacetWP preload/JSON pagination contract. Browser navigation confirmed 10 rows per page, stable detail IDs, and full detail pages. | Activate `airbnb_careers_pages`; use bounded whole-source retries when live inventory changes during pagination. |

## Implemented contracts

`atlassian_careers_inventory` validates the same-origin public collection, stable numeric IDs,
canonical Atlassian detail URLs, iCIMS apply URLs, title/category/description agreement across
portal variants, locations, and complete bundled descriptions. Fifteen duplicate portal variants
were consistent and collapsed. Four jobs lacked a public location and remain explicitly
`location unavailable`. `portalJobPost.updatedDate` is retained with `unknown` date basis because
it is an update field, not verified publication evidence.

`qure_zoho_embedded` locates and validates the unique hidden Zoho inventory, declared fields,
numeric identities, locations, full descriptions, and canonical detail URLs. The browser-proven
Zoho title-slug rule derives the 14 detail URLs; two visibly rendered workflow-flagged rows remain
included because the flags are not visibility gates. `Date_Opened` stays `unknown`.

`airbnb_careers_pages` parses the server-rendered first page and Airbnb's embedded `FWP_JSON`
pagination metadata, then independently replays the public JSON pagination requests used by the
site. It validates page number, page size, total/pages, exact row counts, duplicate IDs, canonical
detail URLs, and a 50-page safety cap. Listing pages defer descriptions until after deterministic
filters. Three representative live detail pages returned 5,329, 6,951, and 8,588 normalized
description characters. Their schema.org `WebPage.datePublished` values remain explicitly
`unknown`, not promoted to job publication dates.

All three new custom adapters have sanitized fixtures and fail-closed tests for malformed schemas,
redirects, inconsistent counts or metadata, duplicate identities, invalid URLs, detail
mismatches, and invalid source configuration. Browser automation is discovery evidence only; no
runtime adapter requires a browser or LLM.

## Activation and validation gates

| Company | Targeted production result | Required-field/date result |
|---|---:|---|
| Atlassian | 285 jobs, 1 page, 1 attempt | 4 explicit unavailable locations; 285 unknown update dates |
| GitLab | 198 jobs, 1 page, 2 attempts | 0 missing; 198 published dates |
| Qure.ai | 14 jobs, 1 page, 1 attempt | 0 missing; 14 unknown dates |
| Airbnb | 158 jobs, 16 pages, 1 attempt | 0 missing; 158 unknown dates; 3 live details passed |

Registry version `0.3.0-phase12-c11` accounts for all 330 canonical companies:

- 129 enabled and 201 disabled records.
- 195 remaining `search_only` sources, four `unresolved`, and two approved `unsupported` sources.
- 35 enabled Greenhouse sources and 14 enabled custom sources.

The complete 129-source production sweep observed **38,071 jobs across 947 pages**. Its raw result
was 124 successful, three verified empty, and two suspicious sources. Every cohort-5 source passed:
Atlassian, GitLab, and Qure.ai in one attempt, and Airbnb in two attempts after one fail-closed
inventory-drift retry. Quantbox Research reproduced the known `stale_publication_dates` anomaly.
Millennium Management exhausted the broad run's retries on a transient duplicate during live
pagination, then passed an independent first-attempt retry with 216 jobs across 22 pages. Effective
health is therefore 125 successful, three verified empty, one known suspicious source, and no
persistent failed, blocked, or partial source.

Ruff formatting and linting passed, strict mypy passed across 108 source files, and the complete
pytest suite reported **563 passed**.

## Commits, rollback, and next step

- `d2ff2c1` adds the Atlassian, Qure.ai, and Airbnb adapters, fixtures, tests, and runtime routing.
- `2674ebb` activates Atlassian, GitLab, Qure.ai, and Airbnb; records LinkedIn's fail-closed reason;
  and updates full-registry accounting.

Reverting `2674ebb` returns the four activated companies to disabled `search_only` records without
removing the reusable adapter code. This cohort is complete. Continue the approved Package C P1/P2
deterministic-source queue. Packages D and E still require explicit approval.
