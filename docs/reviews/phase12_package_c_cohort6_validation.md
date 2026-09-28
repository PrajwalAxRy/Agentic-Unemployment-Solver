# Phase 12 Package C cohort 6 validation

**Status: complete — 6 official deterministic sources activated; 1 candidate failed closed.**

The user approved Packages A, B, and C on 2026-09-28. This sixth Package C cohort assessed
Intuit, Twilio, Roku, Meesho, PhonePe, Swiggy, and Tower Research Capital. Intuit, Twilio, Meesho,
PhonePe, Swiggy, and Tower Research Capital passed their activation gates. Roku remains disabled
and `search_only`. This completes the sixth Package C P1 cohort; additional P1 rediscovery remains.
The user approved continuing through the remaining Package C sources and then Packages D and E on
2026-09-29, subject to the existing public-source, no-bypass, and activation-gate rules.

## Browser discovery and route selection

Discovery used locally installed Playwright Chromium because Windows browser control was not
available. Each official careers surface was rendered and visually inspected. Representative
links, filters, pagination, and public requests were checked with additional screenshots and
network inspection where needed. Every selected request was independently replayed without
cookies or browser state. Screenshots and probe scripts were temporary diagnostics and were not
committed. No authentication, CAPTCHA, rate limit, robots control, WAF, or other access control
was bypassed.

| Company | Browser and public-request evidence | Decision |
|---|---|---|
| Intuit | The official Bengaluru facet reported 29 jobs across exactly two server-rendered pages. Details expose one `JobPosting` JSON-LD object with description, locations, and `datePosted`. | Activate `intuit_bengaluru_pages`; require Bengaluru, India detail locations and publication dates. |
| Twilio | The branded Eightfold UI called public `pcsx/search` and `pcsx/position_details` routes. The UI visibly labels `efcustomTextPostDate` as “Date posted.” | Activate `twilio_public_careers_api`; paginate and reconcile all 131 jobs. |
| Roku | Nine server-rendered pages reconciled 242 global jobs and the Bengaluru facet showed 29, but public detail requests returned an AWS WAF browser challenge. Listings do not contain descriptions. | Fail closed under the no-bypass policy. |
| Meesho | The official jobs page uses the public Lever board `meesho`. | Activate the existing Lever adapter. |
| PhonePe | The rendered official openings page links to the public SmartRecruiters board `PHONEPELIMITED`. | Activate the existing SmartRecruiters adapter. |
| Swiggy | The official page embeds the public MyNextHire careers UI. Browser navigation proved the canonical hash route, and the public requisition collection includes descriptions. | Activate `swiggy_mynexthire_inventory`. |
| Tower Research Capital | The official roles page embeds the public Greenhouse board `towerresearchcapital`. | Activate the existing Greenhouse adapter. |

## Implemented contracts

`intuit_bengaluru_pages` parses the official location facet, validates the declared total and page
count, enforces the expected 15-row page size, rejects duplicate identities, and defers full
description/date/location normalization to detail pages. The official Bengaluru facet is trusted
as the listing scope for rows summarized as “Multiple Locations”; each retrieved detail must still
include Bengaluru or Bangalore, India.

`twilio_public_careers_api` validates the public search schema, reported total, page offsets,
stable position IDs, canonical URLs, duplicates, and a bounded page limit. Details must match the
listing identity and provide a substantive description. Listing creation timestamps remain
unknown evidence; the browser-labelled `efcustomTextPostDate` detail field is published evidence.

`swiggy_mynexthire_inventory` validates the single public requisition collection, stable request
IDs, canonical browser-proven routes, locations, and inline descriptions. `approvedOn` is retained
with unknown date basis. One official description is only “FM to FEM transition”; it remains
visible with the explicit `short_source_description` exception rather than being invented or
silently dropped.

All three custom adapters have sanitized fixtures and fail-closed tests for malformed schemas,
redirects, inconsistent counts, duplicate identities, invalid URLs, detail mismatches, and invalid
source configuration. Browser automation is discovery evidence only; production collection is
deterministic and does not require a browser or LLM.

## Activation and validation gates

| Company | Targeted production result | Required-field/date result |
|---|---:|---|
| Intuit | 29 jobs, 2 pages, 1 attempt | 0 missing; listing dates deferred; 3 live details passed |
| Twilio | 131 jobs, 14 pages, 1 attempt | 0 missing; listing dates unknown; 3 live details passed |
| Meesho | 56 jobs, 1 page, 1 attempt | 0 missing; 56 unknown Lever creation dates |
| PhonePe | 85 jobs, 1 page, 1 attempt | 0 missing; 85 published dates; 3 live details passed |
| Swiggy | 84 jobs, 1 page, 1 attempt | 0 missing; 84 unknown approval dates; 1 short-source exception |
| Tower Research Capital | 91 jobs, 1 page, 1 attempt | 0 missing; 89 published and 2 updated-date fallbacks |

Registry version `0.3.0-phase12-c12` accounts for all 330 canonical companies:

- 135 enabled and 195 disabled records.
- 189 remaining `search_only` sources, four `unresolved`, and two approved `unsupported` sources.
- 36 enabled Greenhouse, 17 enabled custom, 13 enabled Lever, and five enabled SmartRecruiters
  sources.

The complete 135-source production sweep retrieved **38,117 jobs across 986 pages**. Of the 135
sources, 130 succeeded, three returned their verified empty state, and two were suspicious. The
known Quantbox Research stale-publication-date anomaly reproduced. Coupang's public PageUp feed
repeated a duplicate `apijobid` after 53 normalized jobs on all three bounded attempts; an isolated
retry reproduced the same fail-closed result. A later attempt to inspect the raw official feed was
prevented by a temporary DNS failure, so no speculative duplicate suppression was added. The
source remains visible as suspicious pending a byte-level comparison of the upstream duplicate.

Ruff formatting and linting passed, strict mypy passed across 111 source files, and the complete
pytest suite reported **574 passed**.

## Commits, rollback, and next step

- `596e6c4` adds the Swiggy adapter, fixtures, tests, and runtime routing.
- `6313abf` adds the Intuit and Twilio adapters, fixtures, tests, and runtime routing.
- `57be878` activates the six validated sources and records Roku's fail-closed WAF exception.
- `27f3bc2` aligns formatting and complete-registry accounting with the activation.

Reverting `57be878` returns the six activated companies to disabled `search_only` records without
removing the reusable adapter code. Continue the remaining Package C P1/P2 deterministic sources,
then evaluate the now-approved Package D/E lanes under the same fail-closed rules.
