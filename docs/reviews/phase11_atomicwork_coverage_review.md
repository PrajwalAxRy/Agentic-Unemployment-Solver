# Phase 11 Atomicwork coverage exception review

Status: **H4 approved custom-adapter work and H11 approved activation on 2026-09-28. The active
repair and all post-change gates pass.**

Review date: 2026-09-27 (Asia/Calcutta)

Decision date: 2026-09-28 (Asia/Calcutta)

Sanitized repair-request ID: `repair-067463ff973ca40d`

## Recorded H4 decision

The user selected `build Atomicwork custom adapter`. This authorized the bounded implementation,
fixtures, tests, and inactive live validation described in option 1. After reviewing the exact
tested registry diff, the user then replied `approve repair-067463ff973ca40d` at H11.

Implementation commit `fc9734c`, activation commit `d462aa9`, and the complete post-activation
evidence are recorded in `phase11_atomicwork_h11_activation.md`.

## Observed failure

The third-calendar-day pilot attempt `scan-20260927T173616Z-6766cac6` correctly finished as
`partial`: 83 enabled sources succeeded, Deeptune and Rapido were valid-empty, and Atomicwork was
the only failed source. Healthy-source results remained available. The scan observed 26,125 jobs,
found one new identity, displayed no strict or uncertain-date match, and kept 29 review rows
visible.

A targeted Atomicwork verification retried the complete source three times and reproduced:

- adapter: `greenhouse`;
- configured board token: `atomicwork`;
- outcome: `failed`;
- exception: `http_error`;
- failure category: `source_moved`;
- jobs/pages: `0 / 0`.

The sanitized ignored evidence is in:

- `reports/phase11_atomicwork_2026-09-27_targeted.json`;
- `diagnostics/repair_requests/atomicwork_2026-09-27.json`.

## Public official evidence

Read-only requests used public pages, bounded timeouts, and truthful identification. No access
control was bypassed.

- The former public Greenhouse API
  `https://boards-api.greenhouse.io/v1/boards/atomicwork/jobs` now returns HTTP 404.
- The former Greenhouse board and sampled job links redirect to an error page and return HTTP 500.
- Atomicwork's official page, `https://www.atomicwork.com/company/careers`, returns HTTP 200 and
  now contains six job links under `/careers/<id-or-slug>`.
- Atomicwork's public sitemap was last modified on 2026-09-27 and contains exactly the same six
  official job-detail URLs.
- Two sampled official detail pages returned HTTP 200 with matching title, location, and readable
  description content.
- Neither the listing page nor sampled detail pages expose a trustworthy publication date.
- The sampled detail pages still point their Apply action to the retired Greenhouse board, so the
  employer's application link is currently broken. The official Atomicwork detail URLs remain
  readable and usable as report links.

This is a real source redesign, not a temporary network event. Search-engine copies of the old
27-job Greenhouse inventory are stale and are not suitable runtime evidence.

## Why a config-only repair would have been unsafe

The guarded repair overlay may change only `careers_url` and `adapter_parameters`. Pointing the
existing Greenhouse adapter at Atomicwork's Webflow page would misclassify HTML as a Greenhouse
JSON board and would not establish complete inventory, identity, detail, or date behavior.

The registry was not changed until the bounded adapter, fixtures, inactive validation, exact diff,
and rollback were reviewed. H11 then authorized only that tested Atomicwork record change.

## Option 1 — build a bounded custom adapter (recommended)

Implement and validate an inactive `custom` adapter selected by
`adapter_key = "atomicwork_webflow"`:

1. Parse only `https://www.atomicwork.com/company/careers` and same-origin `/careers/...` links.
2. Require the visible Open positions structure and reconcile it with the public sitemap.
3. Preserve each official detail URL as the canonical URL and derive a stable external identity
   from its path.
4. Keep publication evidence `unknown`; use the approved uncertain-date and forward-only
   first-seen policy without inventing a publication timestamp.
5. Fetch the full description only after deterministic role and India-location filters.
6. Fail visibly on off-origin links, duplicate IDs, unexplained empty inventory, missing required
   fields, schema drift, or listing/sitemap disagreement.
7. Add sanitized healthy, empty, malformed, duplicate, off-origin, and detail fixtures before the
   live adapter check.

After tests and a bounded live check pass, prepare this exact active-registry change for the H11
activation checkpoint:

- `careers_url`: `https://job-boards.greenhouse.io/atomicwork` →
  `https://www.atomicwork.com/company/careers`;
- `adapter_type`: `greenhouse` → `custom`;
- `adapter_parameters`: `{ "board_token": "atomicwork" }` →
  `{ "adapter_key": "atomicwork_webflow" }`;
- `date_strategy`: verified `first_published` / `published` → no field / `unknown` / not verified;
- `detail_strategy`: `listing_payload` → `detail_page`;
- evidence and notes: replace the retired-board validation with the reviewed official-page,
  sitemap, fixture, and live-validation evidence.

There are currently zero persisted Atomicwork candidate records in `state/jobs.sqlite3`, so this
adapter-family change does not require a real-state identity migration. That fact must be checked
again immediately before activation. Activation would still require explicit H11 approval after
the implementation, exact diff, fixture results, live results, and rollback are ready.

Estimated scope: one narrow adapter/dispatcher path, fixtures, focused tests, CLI verification
support, one registry update after approval, the custom-adapter group check, and the all-enabled
verification/scan gates.

## Option 2 — mark Atomicwork unsupported for this release

Disable the broken Greenhouse mapping, retain the official careers page as a manual fallback, and
record `source_moved; custom official-page adapter required` as the exception. This reduces
automated enabled coverage from 86 to 85 sources but keeps all 330 canonical companies explicitly
accounted for. It requires explicit approval because Atomicwork is a P1 company and was previously
supported.

## Decision resolution

Option 1 was selected and completed. The official source is public, small, same-origin, and exposes
the fields needed for the bounded adapter. The missing publication date and broken employer Apply
link remain explicit limitations rather than being silently repaired or inferred. The
post-activation 2026-09-28 scan completed with zero failed sources.
