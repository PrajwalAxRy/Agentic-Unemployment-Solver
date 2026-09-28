# Phase 12 Package C cohort 1 validation

**Status: complete — 3 deterministic custom sources activated; 1 candidate failed closed.**

The user approved Packages A, B, and C on 2026-09-28. This first Package C cohort assessed
Amazon / AWS, Google, Apple, and Microsoft. Amazon / AWS, Google, and Apple passed their fixture,
live completeness, detail, date-evidence, registry, and full-repository gates and were activated.
Microsoft's adapter is implemented and tested, but its registry source remains `search_only`
because the final production verification did not pass cleanly. No Package D or Package E work was
activated.

## Activated sources

| Company | Deterministic collection contract | Full-registry live result |
|---|---|---:|
| Amazon / AWS | Official `amazon.jobs` India inventory, count-checked offset pagination, stable job IDs, and public details | 2,374 jobs over 24 pages; all 2,374 dates published |
| Google | Official Google Careers India result pages, count-checked pagination, stable job IDs, and canonical detail URLs | 261 jobs over 14 pages; all dates explicitly unknown |
| Apple | Official server-rendered hydration data, exact-total pagination at 20 jobs per page, stable requisition identities, and public details | 169 jobs over 9 pages; 161 published dates and 8 unknown evergreen-pipeline dates |

The activated cohort accounts for **2,804 current listings** in the all-enabled run. Every listing
had the required identity, title, location, description, and canonical URL fields. Google exposes
no verified publication date in the listing contract, so its dates remain `unknown`. Apple's eight
managed `PIPE-*` evergreen roles expose regenerated timestamps; those values are deliberately not
misrepresented as publication dates.

Each adapter has fixture coverage for malformed responses, pagination and completeness failures,
duplicate identities, required fields, date semantics, and source-specific edge cases. Five
distributed live detail pages were checked for each activated source where the listing contract did
not already contain the complete description.

## Microsoft disposition

Microsoft's official India careers page exposes a public Candidate Experience search API. The
custom adapter uses relevance ordering, stable position IDs, count-checked pagination, public
position details, a minimum interval between request starts, and a rolling request budget.

An isolated live listing validation completed with **233 unique jobs over 24 pages**, and three
representative public detail responses matched their listing identities and supplied descriptions.
The final production-command attempt later received HTTP 429 after 50 jobs because earlier
discovery and validation traffic on the host had consumed the upstream rolling quota. A partial
production gate is not sufficient for activation even when the parser contract has passed.

Microsoft therefore failed closed: the adapter code and fixture tests remain available, but the
registry entry remains disabled and `search_only`. Retry only after a long cooldown, using the
adapter's conservative request budget. Do not bypass the quota or infer activation from the earlier
isolated run.

## Full-registry gate

Registry version `0.3.0-phase12-c3` accounts for all 330 canonical companies:

- 116 enabled sources and 214 disabled backlog or unsupported records.
- 208 remaining `search_only` sources, four `unresolved`, and two approved `unsupported` sources.
- The initial no-retry all-enabled sweep recorded 110 successful, three verified empty, two
  failed, and one suspicious source across 34,944 observed listings and 926 fetched pages.
- Both failures were Greenhouse invalid-JSON responses: Glean and Zeta Global. Immediate bounded
  isolated retries passed on their first attempts with 131 and 141 jobs, respectively, confirming
  transient upstream responses rather than persistent schema changes.
- The final health disposition after the focused retries is 112 successful, three verified empty,
  one suspicious, and no persistent failed, blocked, or partial source.
- The sole suspicious source remains the pre-existing, reviewed Quantbox Research
  stale-publication-date anomaly.
- Amazon / AWS, Google, and Apple all passed in the initial all-enabled sweep without retries.

The raw all-enabled sweep measured 20,995 published, three updated, and 13,946 unknown date values.
The two failed sources contributed no listings to those raw totals; their focused retry reports are
kept as ignored local diagnostics rather than committed data.

Formatting, lint, strict mypy across 99 source files, and the complete test suite passed; pytest
reported **526 passed**.

## Rollback and next step

Adapter implementation and activation are separated into focused commits. Reverting an activation
returns that company to `search_only` without requiring the adapter code to be removed.

This cohort is complete. Continue approved Package C with the next P1/P2 deterministic custom
cohort. Retry Microsoft only after the upstream quota has cooled down. Packages D and E remain
unapproved.
