# Phase 12 comprehensive code and coverage audit

## Outcome

The canonical registry reconciles all 330 companies at version `0.3.0-phase12-c21`:

- 150 enabled deterministic sources;
- 174 disabled `search_only` sources;
- four unresolved identities or official sources; and
- two approved unsupported sources.

Phase 12 has converted 64 of the original 238 `search_only` records into validated live sources:
21 in Package A, six in Package B, and 37 in Package C. No canonical company was removed.

## Audit passes

### 1. Repository and secret hygiene

- Reviewed tracked file types, Git state, ignore rules, dependency declarations, subprocess use,
  direct network paths, exception containment, and common secret patterns.
- No tracked local database, generated report, browser capture, HAR, cookie, environment file,
  API key, or temporary diagnostic was found.
- Production has one runtime dependency (`openai>=2,<3`); browser tooling remains discovery-only
  and is not a production dependency.

### 2. Runtime boundaries and failure semantics

- Centralized public-URL validation for source configuration, normalized job URLs, discovery
  probes, runtime requests, and redirects.
- Literal localhost, loopback, private, link-local, and other non-global IP targets are rejected;
  credential-bearing URLs remain rejected. Redirects are checked before they are followed.
- Added regressions for initial requests, redirect targets, discovery probes, company sources, and
  normalized jobs. Failures remain body-free and URL-safe in diagnostics.
- Reviewed adapter result states, retry behavior, partial-result handling, description retrieval,
  deterministic filters, LLM budget/error behavior, persistence transactions, cache invalidation,
  and full-company accounting. No additional correctness defect was found.

### 3. Configuration and source consistency

- Found and corrected an accidental Adobe note on Microsoft's disabled record.
- Replaced future-dated verification metadata with the actual audit timestamp and corrected the
  registry generation timestamp.
- Added a loader invariant preventing any source verification timestamp from postdating the
  registry generation timestamp.
- Reconciled adapter/status/priority counts, canonical IDs, ranks, custom adapter routing, and the
  original 238-company decision ledger.

### 4. Live source verification

The 149-source full sweep generated at `2026-09-29T06:21:20+05:30` collected 43,447 normalized
jobs across 1,131 pages. It initially reported 143 success, three valid empty, and three suspicious
sources. Follow-up work resolved two transient or upstream-data cases:

- Airbnb's three-attempt sweep encountered a repeated page-2 job ID after ten jobs. An independent
  first-attempt retry completed with 159 jobs across 16 pages.
- Coupang's public XML contained 700 rows and 699 IDs. The duplicate row was identical in ID,
  requisition, URL, title, location, date, and normalized content. The adapter now collapses only
  exact duplicates with a visible warning and still rejects conflicting ID reuse; the live retry
  completed 699 jobs in one attempt.
- Quantbox Research remains intentionally suspicious because all eight active postings carry old
  `first_published` values. Its current `updated_at` values are not silently promoted to
  publication dates.

Confluent was then activated and independently returned 18 jobs in one attempt. Combining the full
sweep with the isolated resolutions gives effective current evidence for all 150 enabled sources:
146 success, three valid empty, one reviewed suspicious, zero failed, zero blocked, and zero
partial; 44,260 jobs across 1,146 pages. The valid-empty sources are Deeptune, Compass, and Rapido.

## Remaining company accounting

The 180 disabled records break down by priority as 16 P1, 76 P2, and 88 P3. The 174
`search_only` records retain these implementation routes:

| Route | Remaining |
|---|---:|
| Deterministic custom adapter (`CA`) | 92 |
| Endpoint replay required (`RD`) | 26 |
| Identity-safe rediscovery (`RS`) | 19 |
| Monitored/manual discovery (`ME`) | 18 |
| Existing adapter candidate (`EA`) | 9 |
| New reusable family (`NF`) | 6 |
| Verified-empty monitor (`TE`) | 4 |

The remaining P1 records are NVIDIA, Meta, Rippling, Zenskar, Microsoft, Zerodha, Kore.ai,
Yellow.ai, LinkedIn, Maxim AI, Roku, Flipkart, Zomato / Blinkit, Mayhem Studios, Mrsool, and X.
Their current fail-closed reasons are recorded in the cohort 12 review. The four unresolved records
are Zenskar, Simplismart, RagaAI, and Info Edge. NVIDIA and PayPal are the two user-approved
unsupported sources.

## Validation

The repository gate runs Ruff formatting and lint, strict mypy, and the complete pytest suite.
The final gate contains 617 passing tests. The package also builds successfully from the locked
project definition. Generated verification JSON remains ignored local evidence under `reports/`.
