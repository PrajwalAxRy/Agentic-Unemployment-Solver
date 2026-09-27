# Implementation progress

## Current status

- Active phase: Phase 11 — full-registry pilot
- Status: Phases 0–10 complete; earlier H1, H2, H4, H5, H6, H9, H10, and H11 decisions remain
  recorded; H8 connectivity is verified. Clean final-profile pilot scans passed on 2026-09-25,
  2026-09-26, and 2026-09-28. The 2026-09-27 partial attempt correctly exposed Atomicwork's moved
  source; H4 approved the bounded adapter and H11 approved exact activation request
  `repair-067463ff973ca40d` on 2026-09-28. All post-change and release-readiness gates pass.
- Pending human checkpoint: H13 first-release approval. Review
  `docs/reviews/phase11_h13_release_readiness.md`. Proposed tag: `v0.1.0`; no tag has been created.
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
- Phase 8 defines the under-five seniority taxonomy, strict JSON response schema, versioned prompt,
  and a 20-case reviewed synthetic evaluation set covering explicit years, alternatives, title/scope
  conflicts, ambiguity, management, and irrelevant dates.
- The provider-neutral evaluator requires verbatim description evidence, retries malformed or
  non-verbatim output once, preserves genuine uncertainty, and routes repeated invalid output to
  manual review. Per-run request/input/output ceilings and sanitized aggregate usage reporting are
  enforced and tested.
- SQLite schema version 2 records model policy. Completed decisions are reused only when job key,
  description hash, search-profile version, prompt version, and model policy all match. Automated
  tests prove that old, role-rejected, and location-rejected jobs never call the model.
- H8 uses AMD's OpenAI-compatible Unified LLM gateway at the user-supplied corporate endpoint,
  with `LLM_GATEWAY_KEY` in both the SDK API-key field and `Ocp-Apim-Subscription-Key` header.
  The initial model is `gpt-5.6-luna`; requests use Chat Completions with strict JSON Schema plus
  mandatory local validation. `.env` and variants remain ignored.
- The redacted H8 presence check found none of the required variables configured. It printed only
  variable names. No live provider request was made, and no credential or response was logged.
- After the user configured the required variables, two redacted H8 connectivity attempts reached
  the gateway but returned HTTP 400. A guarded diagnosis established that the key authenticated,
  the account could list 82 models, and `gpt-5.6-luna` was available. The failure was caused by the
  check's one-token output cap, not by the credential or model entitlement.
- A regression test now requires the connectivity request to use the AMD gateway's confirmed
  16-token minimum. The corrected redacted command passed on 2026-09-23 with provider
  `amd-llm-gateway`, configured model `gpt-5.6-luna`, and returned model
  `gpt-5.6-luna-2026-07-09`. No credential, prompt response, or request header was printed or
  logged. H8 provider configuration and connectivity are complete.
- The guarded Phase 8 validator ran the 20-case reviewed set and a full-registry deterministic
  sampling gate. All 86 enabled sources were healthy (84 successful and two valid empty), with 333
  retained role/location candidates: 115 explicit target roles and 218 conditional-description
  candidates. Conditional-description candidates were not sent to the seniority model because the
  Phase 9 orchestration must first apply their separate deterministic substantive-AI-work check.
- Prompt `1.0.0` initially achieved 18/20 agreement but produced one repeated non-verbatim evidence
  failure and treated a clearly early-career bounded/mentored role as uncertain. Both disagreements
  were already reviewed regression cases. Shared prompt `1.0.1` now encodes the approved no-years
  early-career rule and requires one contiguous exact evidence excerpt; no company-specific rule
  was added.
- Prompt `1.0.1` achieved 20/20 exact `seniority_match` agreement, 20/20 valid schema-and-evidence
  results, zero false acceptances, zero false rejections, and zero ambiguity errors. Detected-level
  agreement was 15/20 and remains diagnostic rather than release-controlling.
- The same eight public jobs were refreshed through their approved adapters and reviewed in full:
  one match, six rejections, and one appropriate uncertainty. Every decision included locally
  verified verbatim evidence; no invalid result or systematic defect remained. The final guarded
  run used 28 requests, 18,523 measured input tokens, and 3,715 measured output tokens. No monetary
  estimate is available for the corporate gateway.
- Repository validation passes at H9 with 406 tests, strict mypy, and Ruff checks.
- H9 was explicitly approved without case-labelled corrections on 2026-09-23. The first-release
  gate is at least 90% exact `seniority_match` agreement, 100% schema-valid results with locally
  verified verbatim evidence, zero false acceptances, zero false rejections, and preservation of
  every labelled ambiguous case as `uncertain`.
- `Uncertain` and invalid seniority results must remain in the dedicated manual-review section and
  must never be promoted to matches. Re-evaluation requires a changed description, profile,
  prompt, or model policy. Prompt `1.0.1` and evaluation set `1.0.0` are the approved Phase 8
  baseline.
- Phase 9 implements the deterministic substantive-AI-work description gate for generic titles,
  end-to-end locked orchestration, schema-version display, bounded flushed progress, durable run
  metrics, human and machine reports, declared exit statuses, and the manual runbook.
- Unchanged completed decisions, H9 uncertain/invalid outcomes, and deterministic description
  rejects are terminal until their policy inputs change. Transient provider and description-fetch
  failures remain visible and retryable; live regressions prove that recovered attempts do not
  repeat prior matches or completed LLM decisions.
- The deliberate fresh-state scan accounted for all 330 companies and all 86 enabled sources. It
  preserved healthy results but correctly returned `partial` when Workday had one transient
  malformed-page failure. A targeted Workday verification passed immediately afterward.
- The same-state recovery scan completed with 84 successful and two valid-empty sources, 26,062
  listings, 335 retained candidates, three genuine new Workday identities, 332 suppressed
  duplicates, and exactly three new LLM evaluations. It reported two new date-uncertain matches.
- The unchanged retry-validation scan completed with zero new identities and zero repeated matches.
  It retried 16 technical outcomes, recovered seven valid decisions, and left only explicit
  provider or unavailable-description review rows for later retry.
- The definitive post-fix scan completed with 84 successful and two valid-empty sources, zero
  source failures, 26,020 listings, 321 retained candidates, zero new identities, 311 suppressed
  duplicates, zero new matches, zero successful LLM re-evaluations, and 166 completed cache hits.
  All 330 company-accounting rows were present; all 244 disabled rows had a nonempty reason.
- The disposable Phase 9 state contains 335 identities: 171 completed, 161 deterministic/terminal
  failures, and three pending provider retries. All four scan-run rows completed durably. No real
  job-history database was reset or replaced, so H7 was not triggered.
- Repository validation passes with 435 tests, strict mypy, Ruff formatting, and Ruff lint at the
  H10 stop.
- H10 was explicitly approved as `usable` on 2026-09-23. The user confirmed that the command,
  report, and runbook made the seven required usability answers clear, completing Phase 9.
- Phase 10 adds stable source failure categories, cross-adapter result-count and publication-date
  anomalies, sanitized schema-v2 verification reports, historical baselines, and bounded source
  retries. Failed or suspicious peers cannot appear healthy and do not hide healthy results.
- Targeted verification supports one company, one adapter family, or all enabled sources. It now
  emits one flushed progress line per company while leaving job-history state untouched.
- Explicit drills cover login and CAPTCHA pages, removed fields, content-type changes, repeated
  pagination, timeout, rate limiting, count collapse, peer isolation, future dates, unavailable
  LLM service, and database lock contention. Diagnostic tests prove configured secrets, messages,
  response bodies, cookies, and credential-like URL query values are not saved.
- The guarded repair workflow creates a deterministic sanitized request, validates an inactive
  exact-diff proposal, and tests supported fields in an immutable in-memory registry. It has no
  activation operation and fails closed on stale values, mismatched IDs/versions, sensitive data,
  duplicate paths, other companies, or unsupported fields.
- The all-enabled live verifier accounted for all 86 enabled companies. It found SAP's configured
  host incompatible with the SuccessFactors parser and retained Quantbox Research as a separate
  reviewed stale-publication-date anomaly. Healthy peers remained usable.
- A post-classifier full rerun confirmed Quantbox has no failure category, then encountered one
  external connectivity event across 21 consecutive unrelated sources after 65 completed results.
  All were retained as `temporary_availability`, not healthy empty results. Immediate checks in
  fresh processes recovered Ashby, Greenhouse, SmartRecruiters, and Darwinbox sources; SAP again
  reached its host and reproduced `unsupported_schema`.
- SAP proposal `repair-1ddc97abb012ee26` changed only the official category host from
  `jobs.sap.com` to `careers.sap.com`. H11 was explicitly approved on 2026-09-25, the exact diff
  was applied in `4c4b2c8`, and the registry regression pins both reviewed values.
- Post-approval targeted SAP and complete SuccessFactors checks each passed with 48 jobs across two
  pages. The final all-enabled verification accounted for all 86 enabled companies, 26,193 jobs,
  and 660 pages: 83 success, two valid empty, zero failures, and one reviewed Quantbox anomaly.
- Repository validation passes with 461 tests, strict mypy, Ruff formatting, and Ruff lint at the
  Phase 10 completion gate. Phase 10 is complete.

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

## Relevant Phase 8 commits

- `6ba4399` — strict seniority taxonomy and response schema
- `40a0a78` — reviewed 20-case seniority evaluation set
- `a3e1c75` — versioned provider-neutral evaluator and mocked retry tests
- `1f13a46` — model-policy-aware decision cache integration
- `a1d663e` — sanitized aggregate request and token usage reporting
- `a0d7803` — initial guarded live-provider configuration and redacted connectivity command
- `29bb0b2` — AMD Unified LLM gateway Chat Completions integration
- `59c9625` — gateway-compatible guarded connectivity limit
- `70c2eaa` — guarded reviewed-set and unseen-batch validation workflow
- `b758042` — approved early-career boundary and contiguous-evidence prompt correction
- `6b427e2` — approved H9 threshold and uncertainty policy

## Relevant Phase 9 commits

- `d07b513` — deterministic substantive-AI-work description gate
- `a93c2bf` — durable manual-scan run metrics
- `9d71103` — terminal review and deterministic outcome persistence
- `e30ba60` — persisted first-seen aging for uncertain dates
- `23dd043` — end-to-end manual scan orchestration
- `3299298` — human-readable scan report
- `3d5c01f` — manual scan command
- `0c7c85c` — scan runbook and troubleshooting
- `2e61261` — bounded scan progress
- `fc9f520` — scan schema-version display
- `e28ac68` — persisted-report and exit-status contract tests
- `7224d43` — retryable transient provider failures
- `8e41ab8` — retryable transient description failures
- `b063434` — flushed long-running progress output
- `1cfe0bc` — explicit reasons for every disabled company

## Relevant Phase 10 commits

- `6afaf3e` — source anomaly detection and failure taxonomy
- `f74c56c` — guarded inactive source repair proposals
- `9807e28` — sanitized source diagnostic reports
- `7ab51cd` — explicit source failure drills
- `d9ea6b8` — immutable testing of inactive repair proposals
- `577d9a0` — separation of source anomalies from failure causes
- `a3b6a3a` — visible bounded source-verification progress
- `4c4b2c8` — approved SAP source-host repair and registry regression

## Phase 11 pilot evidence and commits

- The pilot started from the documented existing schema-3 state with 326 records and did not reset
  duplicate history. Verified local backups were retained before the first run and before post-fix
  scans.
- The first full run on 2026-09-25 accounted for all 330 companies and completed all 86 enabled
  sources: 84 successful, Deeptune and Rapido valid-empty, and zero failed. It observed 26,116
  listings and displayed eight matches for review.
- Review found JPMorganChase Tandem payments development incorrectly admitted by a generic AI
  technology list. `d0ba02e` added the regression and profile `1.1.1` rejection.
- A post-fix scan exposed an uncaught `RemoteDisconnected` at Palo Alto Networks. `719976e` added
  retryable, sanitized containment. The failed scan was durably closed and did not mutate job
  state; three later full scans collected Palo Alto Networks successfully.
- The `1.1.1` immediate rerun suppressed 304 completed decisions but found a new conventional
  Java/AWS full-stack role centered on AI coding assistants. `2161d0e` added a high-fidelity
  regression and final profile `1.1.2`.
- Final-profile run `scan-20260925T135115Z-dc5432db` completed with 84 successful, two valid-empty,
  and zero failed sources; 26,120 listings; 13,380 recency candidates; 1,352 role candidates; 332
  retained candidates; one reviewed valid strict match; no date-uncertain match; and 36 explicit
  review rows. Both fixed false-positive IDs were absent.
- Immediate rerun `scan-20260925T144452Z-39d54451` completed with zero new identities, 311
  suppressed duplicates, zero repeated strict or date-uncertain matches, 169 LLM cache hits, and
  zero failed sources. This passes the duplicate release metric but does not count as a second
  calendar-day pilot.
- Second-day run `scan-20260926T000739Z-2cef6bde` completed with 84 successful, two valid-empty,
  and zero failed sources; 26,194 listings; 13,383 recency candidates; 1,316 role candidates; 314
  retained candidates; zero new identities; 303 suppressed duplicates; no strict or uncertain
  match; and 34 reviewed, visible exception rows.
- All second-day review rows were inspected: 21 detail-location gaps, eight unavailable
  descriptions, two missing locations, two seniority uncertainties, and one retryable gateway
  failure. Two prior gateway failures resolved to explicit seniority uncertainty; no row was
  silently promoted and no new systematic defect was found.
- Final state after the second-day run has 393 records: 22 pending, 195 completed, and 176 failed.
  Pending and failed technical outcomes remain visible and retryable.
- Third-day attempt `scan-20260927T173616Z-6766cac6` finished `partial` with 83 successful, two
  valid-empty, and one failed source; 26,125 listings; 12,896 recency candidates; 1,268 role
  candidates; 295 retained candidates; one new identity; 288 suppressed duplicates; no match;
  and 29 inspected review rows.
- Atomicwork exhausted bounded retries in both the scan and a targeted verifier. Its former
  Greenhouse API returns 404, while the official Atomicwork site and current public sitemap expose
  six Webflow job pages. This is a `source_moved` coverage defect, not an empty board.
- Sanitized request `repair-067463ff973ca40d` was approved at H11. The user first selected the
  bounded custom adapter on 2026-09-28. Commit `fc9734c` added the adapter, eight focused tests,
  and the runtime dispatcher path; commit `d462aa9` activated exactly the reviewed registry diff.
- Inactive and active verification passed in one attempt with six jobs across two pages, zero
  missing fields, listing/sitemap agreement, and six explicit unknown dates. The post-activation
  Greenhouse group had no failure category; all-enabled verification recorded 83 success, two
  valid-empty, one known Quantbox Research anomaly, and zero failed sources across 26,118 jobs.
- The exact registry activation diff, approval, rollback, and completed post-change gates are in
  `docs/reviews/phase11_atomicwork_h11_activation.md`. Full post-activation validation passes Ruff
  format, Ruff lint, strict mypy across 90 source files, and 477 tests.
- Third clean run `scan-20260927T193726Z-8c89b1a8` completed on 2026-09-28 with 84 successful,
  two valid-empty, and zero failed sources; 26,118 listings; 12,683 recency candidates; 1,247 role
  candidates; 293 retained candidates; one new identity; 287 suppressed duplicates; no displayed
  match; and 28 inspected review rows.
- Atomicwork Backend Engineer `4062696008` was the new identity. Its full official description
  confirmed conventional backend/platform work; deterministic `no_ai_topic` rejection is correct.
  No false positive, false negative, source exception, or systematic filter defect was found.
- The 394-record state was backed up and restore-verified before the scan. State now has 395
  records: 21 pending, 196 completed, and 178 failed. No reset, replacement, or migration occurred.
- `d0ba02e` — reject generic AI technology-list false positives
- `719976e` — contain remote source disconnects
- `2161d0e` — reject conventional AI coding-assistant roles

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
- H8 live-provider configuration: `docs/06_llm_provider_configuration.md`
- H9 seniority quality review: `docs/reviews/h9_seniority_quality_review.md`
- H10 manual-scan usability review: `docs/reviews/h10_usability_review.md`
- Phase 10 source resilience and repair runbook: `docs/08_source_resilience_and_repair.md`
- H11 SAP repair review: `docs/reviews/phase10_h11_sap_repair.md`
- Phase 11 full-registry pilot log: `docs/reviews/phase11_pilot_log.md`
- Phase 11 Atomicwork coverage review: `docs/reviews/phase11_atomicwork_coverage_review.md`
- Phase 11 Atomicwork H11 activation review:
  `docs/reviews/phase11_atomicwork_h11_activation.md`
- Phase 11 H13 release-readiness review:
  `docs/reviews/phase11_h13_release_readiness.md`
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
- The definitive Phase 9 report contains six jobs whose public descriptions remain unavailable and
  three Barclays jobs for which the gateway repeatedly returned no completion text. They remain
  explicit review rows; the three provider outcomes are pending and all nine technical outcomes
  are retried by a later scan rather than being silently suppressed or promoted to matches.
- SAP's former `jobs.sap.com` category returned a page schema incompatible with the SuccessFactors
  adapter. H11-approved repair `repair-1ddc97abb012ee26` moved the same official category to
  `careers.sap.com`; post-repair targeted, adapter-group, and all-enabled checks pass.
- Quantbox Research exposes eight active public jobs whose `first_published` values are all old
  while their `updated_at` values remain current. It stays visible as a reviewed
  `stale_publication_dates` anomaly, not an inferred schema failure.
- Clean Phase 11 pilot dates cover 2026-09-25, 2026-09-26, and 2026-09-28. The 2026-09-27 attempt
  remains partial failure-visibility evidence because Atomicwork moved from Greenhouse to official
  Webflow pages. The approved custom adapter restored complete coverage on the third clean day.
- Current pilot review rows include visible Bank of America detail-location gaps, unavailable
  descriptions, intermittent AMD gateway no-completion responses, missing locations, and seniority
  uncertainty. None is silently promoted to a match.

## Resume point

STOP at H13. Release evidence is complete and no tag has been created. Review
`docs/reviews/phase11_h13_release_readiness.md` and choose `approve release, create tag v0.1.0`,
`approve release, no tag`, or `do not release: <reason>`.
