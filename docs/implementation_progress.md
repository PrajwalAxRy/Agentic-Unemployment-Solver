# Implementation progress

## Current status

- Active phase: Phase 4 — Adapter coverage
- Status: Phases 0–3 complete; H1, H2, and H4 approved; Ashby, Greenhouse, Lever, Workday,
  Darwinbox, Eightfold, and SmartRecruiters adapter groups passed. Oracle Cloud is next.
- Pending human checkpoint: None; continue with SmartRecruiters validation.
- No source is enabled. All 330 canonical companies remain in first-release accounting.

## Completed gates

- Repository instructions, design, implementation guide, phased plan, product decisions, and data
  provenance documentation read in full.
- Canonical seed validated: 330 rows, unique IDs/names/ranks, contiguous source order, and priority
  counts P1 96 / P2 106 / P3 128.
- Provenance workbook preserved and its documented SHA-256 checksum verified.
- Phase 0 runtime and tooling established on CPython 3.12 with locked `uv` dependencies.
- Ruff formatting/linting, strict mypy, pytest, smoke commands, ignore rules, and clean-install
  validation established.
- Phase 1 schemas, rolling ten-day recency contract, publication-date measurement contract, and
  approved search-profile examples completed.
- H1 approved on 2026-09-20. Generic engineering/data-science titles use the conditional
  description AI-work lane; `Singapore or Remote` accepts the unqualified remote option.
- Versioned company-source registry loader, adapter-specific parameter validation, complete seed
  reconciler, and disabled registry generator implemented.
- Automated source discovery processed every one of the 330 companies. All 280 Google-search seed
  hints received ranked search evidence and bounded corrective searches where needed.
- Read-only verification used truthful client identification, bounded responses, timeouts, and
  sanitized ignored diagnostics. It did not authenticate or bypass access controls.
- Explicit quality audit rejected third-party, wrong-region, homonym, single-job, and
  non-enumerating false positives.
- Hosted ATS fingerprinting detected 39 unambiguous embedded configurations without retaining page
  bodies. Citi and Arm remained search-only because multiple boards were detected.
- An Adobe-supplied public page exposed a false-positive access classification: dormant CAPTCHA
  configuration in page scripts had been treated as an active challenge. Regression tests now
  distinguish visible challenge pages from script configuration, and all 44 affected sources were
  re-probed successfully with public HTTP 200 responses.
- Phase 3 added a bounded shared HTTP client, adapter runtime interface, fixture-backed Ashby
  parser, and a read-only source-verification command.
- Representative Ashby validation covered valid empty, small, large, and previously oversized
  boards. It found and corrected the case-sensitive Cerebras board name and WisdomAI's current
  hyphenated slug before the full-group run.
- Clipboard Health's former Greenhouse board returned 404. Its official careers page now links to
  the public Ashby `clipboard` board, so it was deterministically remapped and both affected
  adapter cohorts were revalidated.
- Updated full Ashby validation passed 25/25 companies: 24 successful boards, one valid empty
  board, 1,027 observed jobs, zero missing required fields, and 1,027 jobs with `published` date
  evidence. H3 was not triggered because the documented public API established completeness and
  direct links.
- Phase 4 Greenhouse fixtures and adapter cover healthy, empty, malformed, incomplete, duplicate,
  and blocked responses; collection size is verified against `meta.total`, descriptions are
  normalized from the listing payload, and direct job URLs are canonicalized.
- Representative Greenhouse validation passed APT Portfolio, Glean, Motive, Qube Research &
  Technologies, and Pure Storage before the full-family run.
- Full Greenhouse validation passed 25/25 companies with 2,268 jobs and zero missing required
  fields. Of those jobs, 2,265 had `first_published`; one job each at AlphaGrep, Graviton Research
  Capital, and SingleStore retained `updated_at` as an explicit fallback for the H5 date-policy
  review.
- The embedded URLs for Databricks and Graviton Research Capital were corrected to their real
  Greenhouse board tokens. Databricks' 877-job, 9.6 MB response and Pure Storage's 354-job response
  both pass the bounded shared client; the tested maximum is now 20 MB.
- Phase 4 Lever fixtures and adapter cover multi-page results, repeated pages, duplicate IDs,
  pagination limits, access blocks, request failures, HTML description fallback, structured-list
  descriptions, and completely missing descriptions.
- Representative Lever validation passed 100ms, Doxel, and Bazaarvoice after a saved regression
  fixed Bazaarvoice's empty `descriptionPlain` with populated HTML description.
- Full Lever validation passed all 11 current mappings with 386 jobs across 13 fetched pages.
  Lever `createdAt` is retained but all 386 dates remain `unknown` because the public API contract
  does not establish it as publication time. This evidence remains separate for H5.
- BarRaiser exposes 16 jobs and Paytm one job with no description in either the public list or
  detail response. They remain visible with `missing_description` evidence rather than being
  silently rejected.
- Dream Sports' official careers page still links to an obsolete Lever board that returns 404.
  The company remains in the 330-company scope as a documented search-only conflict, while the 11
  current Lever mappings are fully validated.
- Phase 4 Workday fixtures and adapter cover bounded JSON POST pagination, later-page zero totals,
  repeated pages, inconsistent totals, access blocks, partial failures, optional detail retrieval,
  multi-location details, and locations absent from both listing and detail payloads.
- Representative Workday validation passed CrowdStrike, Fractal Analytics, and London Stock
  Exchange Group before the full-family run. The CrowdStrike detail endpoint matched the listing
  identity and supplied full descriptions and additional locations.
- Full Workday validation passed 13/13 companies with 9,198 jobs across 467 pages. All jobs retain
  relative `postedOn` labels as `unknown` date evidence for H5; no detail endpoints or LLM calls
  were used by the full listing validation.
- Fractal Analytics, Barclays, and Cadence each exposed one listing with no location in either the
  list or detail payload. All three remain visible with `Location unavailable`, valid descriptions,
  and direct public links instead of being silently rejected.
- Phase 4 Darwinbox fixtures and adapter cover numbered pagination, stable direct links, public
  detail retrieval, access blocks, repeated pages, total inconsistencies, partial failures, and
  uncertain epoch-valued date evidence.
- Representative Darwinbox validation covered Porter's 121-job paginated board and Rapido's valid
  empty board before the complete group run. A live Porter engineering detail returned a complete
  description and public HTTP 200 deep link.
- Full Darwinbox validation passed 4/4 companies: three successful boards, one valid empty board,
  141 jobs across 17 pages, and zero missing required listing fields. All 141 `job_posting_on`
  values remain `unknown` date evidence for H5.
- Phase 4 Eightfold fixtures and adapter cover count-checked offset pagination, empty and malformed
  responses, repeated pages, access blocks, partial failures, stable IDs and links, uncertain epoch
  dates, and public detail descriptions.
- Millennium Management passed representative and full live validation with 225 jobs across 23
  pages, zero missing required listing fields, and a matching 3,925-character detail description
  for a Bangalore AI role. All 225 `t_create` values remain `unknown` date evidence for H5.
- NVIDIA and PayPal expose public, human-viewable Eightfold careers pages, but their server HTML
  contains no job inventory and the public listing route returns HTTP 403 to the bounded collector.
  H4 was approved on 2026-09-21: both are unsupported for this release with their official careers
  pages retained as manual fallbacks. No access control was bypassed.
- Phase 4 SmartRecruiters fixtures and adapter cover count-checked offset pagination, empty and
  malformed responses, access restrictions, partial failures, duplicate identifiers, direct URLs,
  released-date mapping, and public detail descriptions. Full validation passed Entropik (3 jobs,
  one page), Bosch Global Software Technologies (4,806 jobs, 49 pages), and Freshworks (136 jobs,
  two pages), with zero missing required fields and published `releasedDate` evidence for all 4,945
  observed listings.
- Current proposal accounting reconciles 330/330: 267 auto-verified inventory sources, two
  approved unsupported sources, and 61 conflicts/non-enumerating sources.
- Current source families: Ashby 25, Greenhouse 25, Lever 11, Workday 13, Darwinbox 4, Eightfold 1,
  SmartRecruiters 3, Oracle Cloud 2, SuccessFactors 2, Jobvite 1, search-only 237, unresolved 4,
  unsupported 2.
- Registry remains fully disabled and reconciles all IDs, names, priorities, and source ranks.
- Repository validation passes with 212 tests, strict mypy, and Ruff checks after Eightfold
  validation.

## Relevant Phase 2 commits

- `96a15ff` — source discovery result format
- `d65ebaa` — canonical discovery baseline
- `752b5f2` — bounded public source probes
- `8e18cec` — guarded verification evidence application
- `96f33e7` — initial verified direct-source evidence
- `fe3c4eb` — company registry validator
- `fced9e3` — provisional 330-company registry
- `fd4ed35` — guarded ranked-search importer
- `2697509` — full ranked source-search evidence
- `212a7c6` — search-derived source proposals
- `0ecc04d` — source quality correction gate
- `f89b775` — verification quality audit
- `2f1f7ed` — hosted ATS detection
- `4c9b881` — hosted ATS source-family classifications
- `54bfed6` — completed disabled 330-company source inventory
- `fa76385` — corrected false-positive access detection and revalidated all 44 affected companies

## Relevant Phase 3 commits

- `567e625` — bounded shared source request client
- `93f78cc` — adapter runtime interface and registry
- `c159325` — sanitized Ashby response fixtures
- `509ccef` — shared visible access-block detection
- `33bd50b` — Ashby listing adapter
- `8e5ed5f` — read-only source-verification command
- `0c6a6b8` — guarded adapter validation evidence importer
- `25d0832` — complete Ashby mappings and full-group validation evidence

## Relevant Phase 4 commits

- `c538a6e` — sanitized Greenhouse response fixtures
- `4e4b661` — Greenhouse listing adapter
- `941eed4` — Greenhouse read-only source verification
- `92a10a9` — bounded support for observed large public boards
- `87814f1` — guarded Greenhouse evidence and Phase 4 mapping corrections
- `7da8605` — corrected ATS mappings and full-group validation evidence
- `293148a` — sanitized Lever response fixtures
- `fbe26e2` — paginated Lever listing adapter
- `9cf16c3` — Lever read-only source verification
- `37d28b0` — saved HTML-description regression and fallback
- `1b6a1b0` — structured-list descriptions and explicit missing-description evidence
- `c612f5c` — guarded Lever evidence and conflict mapping support
- `288e57e` — complete Lever mappings and full-group validation evidence
- `f3d5c5d` — exact Workday hosts and corrected locale-prefixed site parameters
- `2edd20f` — bounded JSON POST support in the shared request client
- `39ebcbe` — sanitized Workday list, detail, empty, malformed, and access fixtures
- `a850f5d` — Workday listing and optional detail adapter
- `fdd3e46` — Workday read-only source verification
- `2979f2a` — Workday first-page total and missing-list-location regressions
- `8bbdb2a` — guarded Workday validation evidence importer
- `96d43d5` — complete Workday mappings and full-group validation evidence
- `c44e1f7` — explicit retention of jobs missing detail locations
- `2d97f5b` — bounded support for public same-origin source referers
- `b720b6c` — sanitized Darwinbox list, detail, empty, malformed, and access fixtures
- `363d616` — paginated Darwinbox listing and detail adapter
- `2eb6382` — Darwinbox read-only source verification
- `55b3816` — guarded Darwinbox validation evidence importer
- `2668d06` — complete Darwinbox mappings and full-group validation evidence
- `7b6912a` — sanitized Eightfold list, detail, empty, malformed, and access fixtures
- `ef1e7a3` — paginated Eightfold listing and detail adapter
- `cce24ab` — Eightfold read-only source verification
- `7fbe3e9` — deterministic Eightfold careers URL inference
- `372de97` — corrected PayPal public Eightfold board mapping

## Review artifacts

- H1 search policy review: `docs/reviews/h1_search_policy_review.md`
- Recency and date coverage contract: `docs/05_recency_and_date_coverage_contract.md`
- Phase 1 company schema audit: `docs/reviews/phase1_company_schema_audit.md`
- Source discovery workflow and output contract: `docs/source_discovery_workflow.md`
- H2 source inventory review: `docs/reviews/h2_source_inventory_review.md`
- Phase 3 Ashby validation: `docs/reviews/phase3_ashby_validation.md`
- Phase 4 Greenhouse validation: `docs/reviews/phase4_greenhouse_validation.md`
- Phase 4 Lever validation: `docs/reviews/phase4_lever_validation.md`
- Phase 4 Workday validation: `docs/reviews/phase4_workday_validation.md`
- Phase 4 Darwinbox validation: `docs/reviews/phase4_darwinbox_validation.md`
- Phase 4 Eightfold H4 review: `docs/reviews/phase4_eightfold_h4_review.md`
- Phase 4 SmartRecruiters validation: `docs/reviews/phase4_smartrecruiters_validation.md`
- Full proposal evidence: `data/source_discovery_proposals.json`
- Disabled runtime registry: `config/company_sources.json`

## Unresolved evidence and limitations

- NVIDIA and PayPal are approved unsupported sources for this release because they block the
  reusable Eightfold JSON listing route; their public careers pages remain manual fallbacks. No
  authentication or access-control bypass was attempted.
- 63 companies have conflicting, third-party, wrong-region, non-enumerating, or otherwise
  insufficient source evidence. They remain in scope and disabled.
- All current Ashby and Greenhouse mappings pass their complete adapter-group validations.
- Three observed Greenhouse jobs use update-date evidence because `first_published` is absent.
  They remain separate; no uncertain-date inclusion policy has been selected before H5.
- All 386 observed Lever jobs use uncertain `createdAt` evidence, and 17 lack descriptions. These
  remain explicit inputs to H5 and later manual-review behavior.
- All 9,198 observed Workday jobs use uncertain relative `postedOn` evidence. Three listings lack
  locations in both listing and detail payloads, and multi-location list summaries require detail
  retrieval before deterministic location filtering.
- All 141 observed Darwinbox jobs use uncertain `job_posting_on` evidence; the date values are
  retained but not promoted to publication timestamps before H5.
- All 225 observed Millennium Management jobs use uncertain Eightfold `t_create` evidence. NVIDIA
  and PayPal are excluded from automated listing/date coverage as approved unsupported sources.
- 237 records remain `search_only`; 178 are verified official pages needing custom adapters or
  deeper source-family work, and 59 are conflicts.
- H4 approved NVIDIA and PayPal as unsupported for this release on 2026-09-21; both retain their
  official careers pages as manual fallbacks.

## Resume point

Resume Phase 4 with Oracle Cloud. H4 is complete: NVIDIA and PayPal are approved unsupported
sources with official public careers pages retained as manual fallbacks.
