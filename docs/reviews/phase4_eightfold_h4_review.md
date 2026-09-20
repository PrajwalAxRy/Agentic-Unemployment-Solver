# Phase 4 Eightfold coverage review

## Checkpoint

- Phase: 4 — Adapter coverage
- Checkpoint: H4 — approve a coverage exception
- Status: **STOP — user decision required**
- Decision scope: NVIDIA and PayPal only
- Safe supported source: Millennium Management

## Result summary

| Company | Priority | Public careers page | Automated listing result | Jobs | Pages | Required fields | Date evidence |
|---|---:|---|---|---:|---:|---:|---|
| NVIDIA | P1 | HTTP 200, human-viewable | Blocked before page 1 | 0 | 0 | Not measurable | Not measurable |
| Millennium Management | P2 | HTTP 200 | Complete success | 225 | 23 | 0 missing | 225 `unknown` from `t_create` |
| PayPal | P3 | HTTP 200, human-viewable | Blocked before page 1 | 0 | 0 | Not measurable | Not measurable |

The three-company report reconciles exactly: one complete success and two access blocks. The
sanitized runtime evidence is in `reports/eightfold_full_verification.json` and is intentionally
ignored by Git.

## What was implemented

- Added sanitized healthy, empty, multi-page, malformed, detail, and access-block fixtures.
- Added an Eightfold adapter for the public `/api/apply/v2/jobs` route.
- Added count-checked offset pagination, repeated-page and duplicate-ID detection, partial-failure
  handling, stable identifiers, canonical URLs, deterministic location normalization, and optional
  public detail retrieval.
- Preserved `t_create` as `unknown` date evidence. It has not been promoted to a verified
  publication timestamp before H5.
- Added the adapter to the read-only source-verification command.
- Corrected PayPal's discovered candidate-login URL to its public `/careers` board.

## Representative validation

Millennium Management's ordinary public endpoint reported 225 jobs and returned all 225 across 23
pages with no missing required listing fields. A representative Bangalore role, `Compliance
Analyst (Vendor Management - AI)` (`REQ-31110`), had a matching public detail endpoint with a
3,925-character description. The listing and detail identities matched.

Fixture and repository validation passed:

- 11 focused Eightfold adapter tests.
- 212 total tests.
- Ruff: pass.
- Strict mypy: pass.
- Full 330-company registry audit: pass; no missing or extra company IDs.

## NVIDIA and PayPal limitation

Both companies' official Eightfold `/careers` pages are public and human-viewable. This is not the
earlier Adobe false-positive problem: the pages themselves return HTTP 200, but their
server-rendered HTML contains only the application shell and configuration, not the job
collection. Changing the public `start` offset changes the shell response but still does not embed
the listing payload.

- NVIDIA: `https://nvidia.eightfold.ai/careers`
- PayPal: `https://paypal.eightfold.ai/careers`

The same public JSON listing route that returns Millennium's complete inventory responds with HTTP
403 for NVIDIA and PayPal when called through the bounded collector with a truthful user agent and
same-origin public referer. No authentication, CAPTCHA handling, token reuse, browser-session
export, or other access-control bypass was attempted.

A conventional HTML parser therefore cannot enumerate either board. Continuing automatically
would require a new browser-rendered collection path and company-specific completeness research,
which is materially more custom work than the current reusable HTTP adapter.

## Options and estimated cost

1. **Mark unsupported for this release — recommended.** Record both companies as unsupported but
   retain them in the canonical 330-company accounting, link their official public boards as the
   manual fallback, and revisit if Eightfold exposes a collector-safe public feed. Estimated work:
   less than one engineering hour to record and validate the disposition.
2. **Add custom adapter work now.** Evaluate a browser-rendered collector, then prove pagination,
   detail retrieval, empty/error distinction, and stable behavior independently for NVIDIA and
   PayPal. Estimated investigation and implementation: 2–5 engineering days, plus a browser
   runtime and ongoing maintenance. Success is not assured; work must stop if the browser flow
   encounters CAPTCHA, authentication, or automation controls.
3. **Use native employer alerts.** The user signs up directly on each employer's site; credentials
   stay outside this repository. Estimated user setup: 5–15 minutes per company. This is a manual
   fallback and does not populate the manually triggered product because scheduling and
   notifications are deferred.
4. **Remove from approved scope.** Remove either company from first-release coverage. This is not
   recommended because the approved product decision requires all 330 companies to remain in
   scope.

## Required decision

Choose one disposition for each of NVIDIA and PayPal: add custom adapter work now, mark unsupported
for this release, use a native employer alert, or remove from the approved scope. The recommended
choice is **mark unsupported for this release with the official careers page as the manual fallback
for both companies**.
