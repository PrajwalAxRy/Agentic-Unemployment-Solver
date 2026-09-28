# Phase 12 Package C cohort 7 validation

**Status: complete — 8 official deterministic sources activated.**

This cohort re-ran browser-assisted discovery across the remaining P1 backlog and independently
replayed every selected public request without cookies or browser state. Salesforce, Moloco,
InMobi, Postman, TrueFoundry, Booking.com, Navi, and Quadeye passed their activation gates. The
production collectors are deterministic; browser automation remains discovery evidence only.

## Source decisions

| Company | Deterministic route | Activation evidence |
|---|---|---|
| Salesforce | Existing Workday adapter, tenant `salesforce`, site `External_Career_Site` | Replaced a stale Japan redirect; 1,535 jobs reconciled across 77 pages and three representative details passed. |
| Moloco | Existing Greenhouse adapter, board `moloco` | Official careers page linked the board; complete API returned 39 jobs. |
| InMobi | Existing Greenhouse adapter, board `inmobi` | Official page data and detail links identify the board; complete API returned 72 jobs. |
| Postman | Existing Workday adapter, tenant `postman`, site `careers` | Official open-positions page linked the board; 35 jobs across two pages and three representative details passed. |
| TrueFoundry | Existing Greenhouse adapter, board `truefoundry` | Official page linked CareerPuck; CareerPuck disclosed Greenhouse as the ATS and both public collections contained the same 23 jobs. |
| Booking.com | New `booking_jibe_inventory` adapter | Public Jibe API reconciled its company hierarchy filter, 94-job total, ten pages, stable requisition IDs, inline descriptions, and canonical URLs. |
| Navi | New `navi_public_careers_api` adapter | Same-origin API reconciled `Total`, `FilteredCount`, and all 41 jobs with UUID identities, locations, descriptions, and publication timestamps. |
| Quadeye | New `quadeye_zoho_proxy` adapter | Same-origin Zoho proxy returned the same 26 published jobs rendered by the official page, including descriptions and browser-matching detail routes. |

## Regression findings

The first Navi production gate stopped after one job because the second record used the official
company label `Navi Limited` rather than `Navi`. A fixture now covers both accepted Navi-owned
labels; the full retry passed all 41 jobs. The first Quadeye gate stopped after 15 jobs because one
browser-visible, `Publish=true` record had ATS status `On-Hold`. A fixture now proves that published
visibility, not the workflow status, is the public-inventory contract. The adapter preserves that
status as metadata and the full retry passed all 26 jobs. No malformed job was silently skipped.

## Adapter guarantees

`booking_jibe_inventory` requires the official company-hierarchy filter, stable totals on every
page, exact ten-row pagination except for the final page, a bounded 100-page maximum, unique
numeric requisition IDs, official canonical/apply URLs, inline descriptions, and timezone-aware
`posted_date` publication timestamps.

`navi_public_careers_api` requires matching `Total`, `FilteredCount`, and collection length, unique
UUIDs, Navi-owned company labels, parsed location JSON, matching public TurboHire URLs, inline
descriptions, and timezone-aware `PublishedDate` values.

`quadeye_zoho_proxy` requires `success=true`, `Publish=true`, unique numeric Zoho IDs, matching
posting/opening titles, non-empty locations and descriptions, and deterministic official detail
URLs. `Date_Opened` remains explicit **unknown-basis** date evidence; it is not mislabeled as a
publication date.

All three new adapters fail closed on redirects, schema drift, duplicates, incomplete pagination,
identity mismatch, invalid URLs, and malformed dates. Sanitized fixtures cover their successful
and adversarial contracts.

## Live gate and accounting

The targeted production gates covered **1,865 jobs across 94 pages**:

- Salesforce: 1,535 jobs, 77 pages, three representative details; relative Workday dates remain
  uncertain.
- Moloco: 39 jobs, one page.
- InMobi: 72 jobs, one page.
- Postman: 35 jobs, two pages, three representative details; relative Workday dates remain
  uncertain.
- TrueFoundry: 23 jobs, one page, 23 published dates.
- Booking.com: 94 jobs, ten pages, 94 published dates.
- Navi: 41 jobs, one page, 41 published dates.
- Quadeye: 26 jobs, one page, 26 unknown-basis `Date_Opened` values.

Registry version `0.3.0-phase12-c16` accounts for all 330 canonical companies:

- 143 enabled and 187 disabled records.
- 181 remaining `search_only` sources, four `unresolved`, and two approved `unsupported` sources.
- 39 enabled Greenhouse, 23 Workday, and 20 custom sources.

Ruff formatting and linting passed, strict mypy passed across 114 source files, and the repository
suite contains **584 tests**. A complete all-enabled production sweep follows this cohort before
the next activation group.

## Rollback and next step

Revert the cohort's registry changes to disable these eight sources without removing reusable
adapter code. Continue deterministic P1/P2 discovery first, then the user-approved Package D/E
lanes. Any source without a provably complete public contract remains disabled with a reason.
