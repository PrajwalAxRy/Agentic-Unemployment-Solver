# Phase 12 Package C cohort 2 validation

**Status: complete — 3 deterministic custom sources activated; 1 candidate failed closed.**

The user approved Packages A, B, and C on 2026-09-28. This second Package C cohort assessed
Stripe, ServiceNow, Coupang, and Flipkart. Stripe, ServiceNow, and Coupang passed discovery,
fixture, live completeness, identity, description, date-evidence, registry, and full-repository
gates and were activated. Flipkart remains disabled and `search_only` because its current official
jobs page does not expose a usable deterministic inventory contract. Packages D and E remain
unapproved.

## Discovery evidence and route selection

The attempted Windows browser-control capture could not reactivate the captured Edge window, so no
durable screenshot or click trace was claimed. Discovery continued through the rendered official
pages and bounded public official HTTP responses. No authentication, CAPTCHA, rate limit, robots
control, or other access restriction was bypassed.

| Company | Rendered-page evidence | Selected deterministic route |
|---|---|---|
| Stripe | Official search rendered 62 UI pages | Server-rendered `__NEXT_DATA__` index plus canonical public detail pages |
| ServiceNow | Official India location page rendered 68 jobs | Same-host official PageUp XML export |
| Coupang | Official Bengaluru page rendered 28 jobs | Same-host official PageUp XML export |
| Flipkart | Official page displayed 69 openings | None; failed closed because rows expose no job-detail links and `showMore()` only displays a placeholder alert |

The PageUp/Happydance HTML query parameters did not reliably constrain direct replay, so the HTML
pagination route was rejected. ServiceNow and Coupang each advertise a same-host
`/jobs/xml/?rss=true` export containing the complete global inventory, stable API job IDs,
canonical URLs, RFC 2822 publication dates, locations, and full descriptions.

Stripe's server-rendered search index contained 653 global jobs across 103 location definitions,
including 41 India jobs. It provides stable Greenhouse IDs and canonical
`/careers/listing/{slug}/{id}` URLs. Publication dates and full descriptions are deliberately
deferred to matching public detail pages. Five distributed India detail samples matched listing
identity and location data, supplied 2.9–5.3 KB normalized descriptions, and exposed matching
JobPosting `datePosted` values.

## Implemented contracts

`pageup_xml_feed` performs one bounded same-host XML request, rejects DTD/entity declarations,
validates the publisher and build timestamp, checks stable numeric identities and official URLs,
normalizes full descriptions, and treats malformed or duplicate rows as incomplete/suspicious.
The fixture includes a percent-encoded Korean Coupang slug captured from the live feed; a failing
regression was recorded before the URL validator was narrowly extended to accept valid encoded
Unicode slug characters.

`stripe_careers_index` requires the exact official search page, exactly one expected Next.js data
block, valid filter indices, stable numeric identities, and canonical detail paths. Detail
retrieval cross-checks ID, slug, title, locations, structured JobPosting identity, publication
date, and description. An unapproved redirect regression was demonstrated before adding the
fail-closed diagnostic path.

## Activation gates

| Company | Targeted production result | Required fields | Date result |
|---|---:|---:|---|
| Stripe | 653 jobs, 1 page, 1 attempt | 0 missing | 653 intentionally unknown until detail retrieval |
| ServiceNow | 685 jobs, 1 page, 1 attempt | 0 missing | 685 published |
| Coupang | 702 jobs, 1 page, 1 attempt | 0 missing | 702 published |

Registry version `0.3.0-phase12-c6` accounts for all 330 canonical companies:

- 119 enabled and 211 disabled records.
- 205 remaining `search_only` sources, four `unresolved`, and two approved `unsupported` sources.
- Seven enabled custom-adapter sources.
- Flipkart remains among the disabled `search_only` records with an explicit exception reason and
  fresh verification note.

The complete 119-source production sweep observed **37,260 jobs across 929 pages**: 115 sources
succeeded, three were verified empty, and one was suspicious. There were no failed, blocked, or
partial sources. The sole suspicious source is the unchanged reviewed Quantbox Research
`stale_publication_dates` anomaly. The sweep measured 22,648 published dates, three updated-date
fallbacks, and 14,609 unknown dates. All three newly activated sources passed in one attempt with
zero missing required fields.

Ruff formatting and linting passed, strict mypy passed across 101 source files, and the complete
pytest suite reported **535 passed**.

## Commits, rollback, and next step

- `1c58608` adds the PageUp XML and Stripe careers adapters, fixtures, regressions, and runtime
  registration.
- `f667fc6` activates Stripe, ServiceNow, and Coupang and records Flipkart's failed-closed reason.
- `4c52788` updates the disabled-company accounting invariant to 211.

Reverting `f667fc6` returns the three companies to `search_only` without removing the reusable
adapter code. This cohort is complete. Continue the user-approved Package C P1/P2 backlog with the
next deterministic custom-source cohort. Packages D and E still require explicit approval.
