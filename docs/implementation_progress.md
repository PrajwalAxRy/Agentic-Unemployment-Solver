# Implementation progress

## Current status

- Active phase: Phase 8 — LLM seniority evaluation
- Status: Phases 0–7 complete; H1, H2, H4, H5, and H6 approved. Phase 8 is ready to begin.
- Pending human checkpoint: none. H7 applies only if progress requires a destructive action on
  real job-history state; Phase 7 development and tests must use disposable state.
- The 86 validated adapter sources are enabled. All 330 canonical companies remain in
  first-release accounting, including 244 disabled backlog or unsupported records.

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
- Phase 4 Oracle Cloud fixtures and adapter cover public Candidate Experience list and detail
  resources, stable requisition IDs and direct links, count-checked offset ranges, active-inventory
  total drift, short nonterminal pages, access restrictions, malformed jobs, duplicate and repeated
  pages, and published date-only values.
- Full Oracle Cloud validation passed Uber (532 jobs, three pages) and JPMorganChase (7,355 jobs,
  37 pages) with zero missing required fields and published `PostedDate` evidence for all 7,887
  observed listings. One public detail from each source matched its listing identity and supplied a
  readable full description. H3 and H4 were not triggered.
- Phase 4 SuccessFactors fixtures and adapter cover range-checked HTML pagination, stable numeric
  posting IDs and public links, empty and malformed pages, access blocks, partial failures,
  duplicate identities, page limits, and public detail-page dates and descriptions.
- Full SuccessFactors validation passed SAP's India category with 46 jobs across two pages and zero
  missing required listing fields. The list omits dates, so all 46 remain `unknown` until detail
  retrieval. A sampled detail matched posting `1280449101`, exposed a published schema.org
  `datePosted`, and supplied a 9,843-character normalized description.
- Moody's official inventory is a Radancy search site. Its embedded SuccessFactors URL is only a
  returning-applicant login, so the false-positive mapping was corrected to `search_only` and kept
  in the H2-approved custom-discovery backlog. No source was removed and H4 was not triggered.
- Phase 4 Jobvite fixtures and adapter cover the complete public board, stable link identities,
  malformed or incomplete rows, duplicate IDs, unexpected pagination controls, access blocks,
  public detail dates, and detail descriptions. SiMa.ai passed full validation with 18 jobs, one
  page, and no missing listing fields; its sampled detail supplied a published schema.org date and
  a 1,705-character normalized description.
- A single enabled-registry verifier now exercises all adapter families through the shared runtime
  contract. Saved regressions handle active-inventory total drift in SmartRecruiters and Workday,
  while exact identifier-only Workday placeholders remain visible as warnings but are not emitted
  as usable jobs.
- The fresh Phase 4 full-registry run passed all 86 enabled companies: 84 successful sources, two
  valid empty sources, 26,107 jobs, 661 pages, and zero failed, blocked, partial, or suspicious
  companies. Date evidence was 16,142 published, three updated, and 9,962 unknown listings; those
  measurements are inputs to Phase 5 and do not preselect an H5 policy.
- Phase 5 added shared Unicode, punctuation, whitespace, title, multi-location alias, URL, and
  timestamp normalization while preserving all source-original fields and date precision.
- The rolling recency measurement command applies one completion-time boundary after collection,
  records every listing's evidence and decision without descriptions, and reports company,
  adapter, listing, identity, URL, first-seen, and ten-day metrics. A saved regression prevents jobs
  published during a long scan from being falsely classified as future.
- Bounded complete-source retries recover intermittent invalid payloads and active-pagination
  churn without retrying access blocks. Oracle Cloud now requests explicit oldest-first ordering;
  when Oracle reports inventory-total drift, duplicate IDs remain visible warnings and each unique
  listing is retained once after every requested offset is fetched.
- The final Phase 5 live gate passed 86/86 companies with 84 successful and two valid-empty
  sources. It observed 26,122 jobs, all with valid identities and URLs, with zero invalid dates and
  zero unassessed companies. One Greenhouse source recovered on its second bounded attempt.
- Company date coverage is 49 all-reliable (56.98%), five mixed (5.81%), 30 no-reliable (34.88%),
  two no-listings (2.33%), and zero unassessed. Listing evidence is 15,911 reliable (60.91%),
  10,146 uncertain (38.84%), zero invalid, and 65 missing (0.25%). The interim decisions are 2,326
  inside, 13,585 outside, and 10,211 uncertain. First-seen availability is zero in the initial
  baseline.
- H5 recommends a documented hybrid policy but does not select it: strict verified publication
  dates, a separate uncertain section, post-filter detail dates for Jobvite and SuccessFactors,
  and forward-only first-seen aging for the persistently uncertain adapter families.
- Current registry accounting reconciles 330/330: 86 reusable adapter mappings, 238 search-only
  records, four unresolved records, and two approved unsupported sources.
- Current source families: Ashby 25, Greenhouse 25, Lever 11, Workday 13, Darwinbox 4, Eightfold 1,
  SmartRecruiters 3, Oracle Cloud 2, SuccessFactors 1, Jobvite 1, search-only 238, unresolved 4,
  unsupported 2.
- All 86 validated adapter mappings are enabled. The registry still reconciles all IDs, names,
  priorities, and source ranks; the other 244 records remain explicitly disabled.
- Repository validation passes with 262 tests, strict mypy, and Ruff checks at checkpoint H5.
- H5 option 4 was approved on 2026-09-22 and recorded as search-profile version `1.1.0`.
- The post-decision full-registry recency run passed all 86 enabled companies: 84 successful, two
  valid empty, 25,952 listings, 25,952 valid identities and URLs, and zero invalid dates or
  unassessed companies. Evidence was 15,981 reliable, 9,906 uncertain, and 65 missing; decisions
  were 2,432 inside, 13,549 outside, and 9,971 uncertain. Bank of America recovered on its third
  bounded attempt.
- Phase 6 implements exclusion-first role-family filtering, the approved generic-title
  conditional-description lane, deterministic India location handling, remote and hybrid policy,
  multi-location handling, and machine-readable reasons while retaining source-original fields.
- Live sample review found and fixed shared location defects for foreign restricted-remote roles,
  the word `Global` inside non-India locations, Workday's structured `IN - Remote - IND` value,
  and Workday multi-location summaries. Jobvite and SuccessFactors detail dates are fetched only
  after deterministic role and location eligibility, as approved at H5.
- The corrected Phase 6 complete-registry run passed all 86 enabled companies with 84 successful
  and two valid-empty outcomes. It observed 25,960 listings, yielding 2,461 strict-recent and 9,964
  uncertain-date candidates after 13,535 recency exclusions. Role filtering produced 426 explicit
  passes, 831 conditional-description candidates, and 11,168 rejections.
- Location filtering reduced the 1,257 role-eligible candidates to 329 retained, 19 explicit
  location reviews, and 909 location rejections; 12,077 candidates were rejected overall. The
  retained set covers all nine approved role families or lanes and all three accepted-location
  evidence categories.
- Phase 6 used 149 post-role location/date detail lookups. Seventeen Bank of America Workday
  multi-location details were unavailable and remain visible for location review; two SAP detail
  date failures remain in the H5-approved uncertain-date lane. No candidate was silently dropped.
- Fifty-one companies have no retained jobs: 17 have no recency candidates, 22 have no eligible
  role titles, 11 have eligible roles only outside India, and Bank of America has location-review
  candidates but no deterministic pass. The H6 artifact samples 30 retained, 30 rejected, and all
  19 review rows with unique correction labels.
- Repository validation passes at the H6 stop with 323 tests, strict mypy, and Ruff formatting and
  lint checks.
- H6 was explicitly approved without row-labelled corrections on 2026-09-22. Search-profile
  version `1.1.0` and the report's recorded profile hash are the approved Phase 6 baseline.
- Phase 7 added versioned SQLite migrations, stable source-aware job keys, transactional pending
  and completed evaluation state, cache invalidation, an operating-system scan lock, and guarded
  inspection, backup, restore, and reset commands.
- The live persistence history accumulated 336 stable identities, all using external requisition
  IDs. No live URL or fallback fingerprint was needed; fixture regressions cover those lower-priority
  strategies and prevent accidental merges.
- Live validation exposed Workday overlap during active inventory drift. A regression preceded the
  shared fix: every requested offset is fetched, each unique job is retained once, and overlap is a
  warning only when the source also reports inventory drift.
- The final Phase 7 complete-registry continuation passed all 86 sources with 84 successful and two
  valid-empty outcomes, 26,051 listings, 333 retained candidates, and zero new identities against
  the 336-record disposable history.
- A documented disposable-state backup and restore preserved all 336 records and schema version 1.
  No real history was modified, so H7 was not triggered.
- Repository validation passes at Phase 7 completion with 356 tests, strict mypy, and Ruff checks.

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
- `6f533af` — SmartRecruiters adapter and full-group validation evidence
- `af9a9a7` — sanitized Oracle Cloud response fixtures
- `979342c` — Oracle Cloud listing and detail adapter
- `83aac4c` — Oracle Cloud read-only source verification
- `b7e0999` — active-inventory and short-page pagination regressions
- `1243695` — complete Oracle Cloud mappings and full-group validation evidence
- `5353c88` — sanitized SuccessFactors HTML response fixtures
- `eb5a181` — SuccessFactors listing and detail-page adapter
- `ce0d8ed` — SuccessFactors read-only source verification and Moody's mapping correction
- `e113f55` — complete SuccessFactors mapping and full-group validation evidence
- `177dde5` — sanitized Jobvite response fixtures
- `b54a63e` — Jobvite listing and detail-page adapter
- `14ad6d2` — Jobvite read-only source verification
- `4ca97cf` — complete Jobvite mapping and full-group validation evidence
- `e69c04e` — enabled-registry listing verifier
- `01209d3` — active-inventory drift and identifier-only placeholder regressions
- `b95429c` — activation of all 86 validated Phase 4 sources

## Relevant Phase 5 commits

- `6f92ab8` — shared source-independent job normalization
- `a4f2e96` — registry-wide recency measurement and reporting
- `59ffbc1` — read-only recency measurement command
- `bf6a990` — completion-time boundary for long live scans
- `181f629` — bounded retry of unstable complete-source scans
- `8e70f8e` — stable ordering and drift-aware Oracle pagination

## Relevant Phase 6 commits

- `3309c02` — role-family title filtering and title exclusions
- `fd74adc` — India location and work-mode filtering
- `39b46fa` — complete-registry filter verification and H6 report generation
- `3760094` — live location regressions and selective detail resolution

## Relevant Phase 7 commits

- `6d868af` — versioned job-state database migrations
- `5e2d852` — stable source-aware job identity mapping
- `7833680` — transactional pending and completed evaluation state
- `4eef485` — cross-process scan lock
- `0685b4b` — guarded state maintenance commands
- `1960345` — two-pass full-registry persistence verifier
- `d2c6ccf` — per-source drift evidence and continuation support
- `d7d3483` — clean single-pass continuation gate
- `3ff0355` — drift-aware Workday overlap handling

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
- Phase 4 Oracle Cloud validation: `docs/reviews/phase4_oracle_cloud_validation.md`
- Phase 4 SuccessFactors validation: `docs/reviews/phase4_successfactors_validation.md`
- Phase 4 Jobvite validation: `docs/reviews/phase4_jobvite_validation.md`
- Phase 4 adapter coverage completion: `docs/reviews/phase4_adapter_coverage_completion.md`
- H5 publication-date coverage review: `docs/reviews/h5_date_coverage_review.md`
- H6 role and location filter review: `docs/reviews/h6_filter_review.md`
- Phase 7 duplicate-persistence validation: `docs/reviews/phase7_persistence_validation.md`
- Full proposal evidence: `data/source_discovery_proposals.json`
- Active source registry and explicit backlog: `config/company_sources.json`

## Unresolved evidence and limitations

- NVIDIA and PayPal are approved unsupported sources for this release because they block the
  reusable Eightfold JSON listing route; their public careers pages remain manual fallbacks. No
  authentication or access-control bypass was attempted.
- 63 companies have conflicting, third-party, wrong-region, non-enumerating, or otherwise
  insufficient source evidence. They remain in scope and disabled.
- All current Ashby and Greenhouse mappings pass their complete adapter-group validations.
- Three observed Greenhouse jobs use update-date evidence because `first_published` is absent.
  They remain separate; no uncertain-date inclusion policy has been selected before H5.
- All 372 observed Lever jobs use uncertain `createdAt` evidence. Missing descriptions remain
  explicit later manual-review inputs.
- All 9,166 observed Workday jobs use uncertain relative `postedOn` evidence. Three listings lack
  locations in both listing and detail payloads, and multi-location list summaries require detail
  retrieval before deterministic location filtering.
- All 141 observed Darwinbox jobs use uncertain `job_posting_on` evidence; the date values are
  retained but not promoted to publication timestamps before H5.
- All 225 observed Millennium Management jobs use uncertain Eightfold `t_create` evidence. NVIDIA
  and PayPal are excluded from automated listing/date coverage as approved unsupported sources.
- Of 7,911 observed Oracle Cloud jobs, 7,672 have decidable documented `PostedDate` evidence and
  239 date-only values overlap the exact ten-day timestamp boundary. The JPMorganChase board can
  change totals during a scan and return short or overlapping pages; those behaviors remain
  visible while every requested offset, unique ID, and repeated page is checked.
- All 47 observed SAP listing rows omit a publication date. The public detail page supplies a
  verified schema.org `datePosted`, so recency requires detail retrieval after the deterministic
  title and India-location gates.
- Moody's remains an explicit `search_only` custom-discovery item after its returning-applicant
  SuccessFactors login was rejected as an inventory source.
- SiMa.ai's 18 Jobvite listings omit dates; its public detail pages provide structured published
  dates, which Phase 5 may retrieve only after deterministic pre-detail filters.
- Seventeen Bank of America multi-location candidates could not retrieve their public Workday
  details during the Phase 6 scan and remain explicit H6 location-review rows. Two SAP detail-date
  fetches failed and remain explicit uncertain-date candidates under the approved hybrid policy.
- 238 records remain `search_only`; 179 are verified official pages needing custom adapters or
  deeper source-family work, and 59 are conflicts.
- H4 approved NVIDIA and PayPal as unsupported for this release on 2026-09-21; both retain their
  official careers pages as manual fallbacks.

## Resume point

Begin Phase 8 by defining the structured seniority taxonomy and response schema from the approved
under-five-years examples. Continue with a mocked evaluator before any live provider request, then
build the labelled evaluation set and stop at H9 with the required quality report.
