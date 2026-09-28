# Phase 12 Package C cohort 4 validation

**Status: complete — 4 official deterministic sources activated.**

The user approved Packages A, B, and C on 2026-09-28. This fourth Package C cohort activated
Altimate.ai through its officially linked Ashby board and added deterministic custom adapters for
Aganitha, GalaxEye, and Gnani.ai. Packages D and E remain unapproved.

## Browser discovery and route selection

Discovery used a locally installed Playwright Chromium browser because Windows browser control was
not available. The official pages were rendered and visually inspected, job links were clicked,
and representative listing and detail screenshots were inspected locally. Screenshots were
temporary diagnostics and were not added to the repository. Public requests were then replayed
without cookies or browser state. No authentication, CAPTCHA, rate limit, robots control, or other
access restriction was bypassed.

| Company | Browser evidence | Selected deterministic route |
|---|---|---|
| Altimate.ai | Official careers page linked to `jobs.ashbyhq.com/altimate` | Existing Ashby adapter with organization `altimate` |
| Aganitha | Official careers page rendered nine accordion jobs and canonical detail links | Server-rendered careers index plus bounded detail-page parsing |
| GalaxEye | Official site linked to its branded Zoho Recruit board, which advertised a same-host RSS feed | Official Zoho Recruit RSS collection with bundled descriptions |
| Gnani.ai | Official careers UI rendered 36 positions and working detail pages | Public `/api/jobs` inventory plus server-rendered job details |

## Implemented contracts

`aganitha_careers_index` validates the exact official listing URL, stable canonical detail slugs,
listing/detail title compatibility, locations, complete descriptions, and duplicate identity. The
listing does not publish dates, so all nine dates remain explicitly `unknown`. Two legitimate
listing/detail title variations are normalized conservatively and remain visible through the
`title_variation_normalized` diagnostic.

`galaxeye_zoho_rss` validates the officially linked Zoho publisher, stable numeric GUIDs,
canonical job URLs, locations, RFC 2822 `pubDate` values, complete bundled descriptions, and
duplicate identity. The direct job HTML is a JavaScript shell, so the official RSS descriptions are
used instead of pretending that the shell contains a deterministic detail contract.

`gnani_careers_api` checks the API success envelope, declared total, unique stable position codes,
publication dates, canonical detail URLs, and detail-page identity and description sections. Ten
API rows had a null location while the rendered official UI labeled the same rows `Remote`; the
adapter records that evidenced mapping as `null_location_is_remote` rather than silently filling
the field.

All three custom adapters have sanitized listing/detail fixtures and fail-closed tests for malformed
schemas, redirects, duplicate identities, count mismatches, title/detail mismatches, and invalid
source configuration.

## Activation and validation gates

| Company | Targeted production result | Required fields | Date result |
|---|---:|---:|---|
| Altimate.ai | 5 jobs, 1 page, 1 attempt | 0 missing | 5 published |
| Aganitha | 9 jobs, 10 pages, 1 attempt | 0 missing | 9 unknown |
| GalaxEye | 69 jobs, 1 page, 1 attempt | 0 missing | 69 published |
| Gnani.ai | 36 jobs, 1 page, 1 attempt | 0 missing | 36 published |

Registry version `0.3.0-phase12-c10` accounts for all 330 canonical companies:

- 125 enabled and 205 disabled records.
- 199 remaining `search_only` sources, four `unresolved`, and two approved `unsupported` sources.
- 27 enabled Ashby sources and 11 enabled custom sources.

The 125-source production sweep completed the first 87 sources with 85 successes, one valid empty
source, and the known Quantbox Research `stale_publication_dates` anomaly. All four cohort sources
passed within that sweep. A later 38-source tail reported the same
`temporary_availability/network_error` category. Independent retries proved that the tail was not
a cohort regression: Clipboard Health passed with 36 jobs, Bank of America passed with 1,986 jobs
across 100 pages, and JPMorganChase passed with 7,495 jobs across 38 pages. Quantbox independently
reproduced its eight-job stale-date anomaly. The broad sweep remains preserved as truthful
transient-failure evidence rather than being relabeled as a clean run.

Ruff formatting and linting passed, strict mypy passed across 105 source files, and the complete
pytest suite reported **552 passed**.

## Commits, rollback, and next step

- `a1cf513` activates Altimate.ai through its official Ashby board.
- `b0d1159` adds the Aganitha, GalaxEye, and Gnani.ai adapters, fixtures, tests, and runtime routing.
- `3ef3a56` activates the three custom sources and updates full-registry accounting.
- `7cddf3f` applies the repository's canonical formatter to the new adapter cohort.

Reverting `3ef3a56` and `a1cf513` returns the four companies to disabled `search_only` records
without removing the reusable adapter code. This cohort is complete. Continue the approved Package
C P1/P2 deterministic-source queue. Packages D and E still require explicit approval.
