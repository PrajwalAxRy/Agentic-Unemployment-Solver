# Implementation progress

## Current status

- Active phase: Phase 2 — Company source inventory
- Status: Phases 0 and 1 complete; H1 approved; Phase 2 automated discovery and validation
  complete; stopped at mandatory checkpoint H2
- Pending human checkpoint: H2 — approve sources, access dispositions, custom-source backlog, and
  adapter priority
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
- Final proposal accounting reconciles 330/330: 216 auto-verified, 44 access concerns, 68
  conflicts/non-enumerating sources, and 2 responsive but oversized structured boards.
- Final source families: Ashby 24, Greenhouse 26, Lever 12, Workday 13, Darwinbox 4, Eightfold 3,
  SmartRecruiters 3, Oracle Cloud 2, SuccessFactors 2, Jobvite 1, search-only 236, unresolved 4.
- Registry remains fully disabled and reconciles all IDs, names, priorities, and source ranks.
- Repository validation passes with 93 tests, strict mypy, and Ruff checks at H2.

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

## Review artifacts

- H1 search policy review: `docs/reviews/h1_search_policy_review.md`
- Recency and date coverage contract: `docs/05_recency_and_date_coverage_contract.md`
- Phase 1 company schema audit: `docs/reviews/phase1_company_schema_audit.md`
- Source discovery workflow and output contract: `docs/source_discovery_workflow.md`
- H2 source inventory review: `docs/reviews/h2_source_inventory_review.md`
- Full proposal evidence: `data/source_discovery_proposals.json`
- Disabled runtime registry: `config/company_sources.json`

## Unresolved evidence and limitations

- 44 public pages triggered an access-control/login/CAPTCHA marker. They remain disabled; no bypass
  was attempted.
- 68 companies have conflicting, third-party, wrong-region, non-enumerating, or otherwise
  insufficient source evidence. They remain in scope and disabled.
- Harvey (Ashby) and Pure Storage (Greenhouse) returned public structured responses larger than the
  two-megabyte discovery cap. They require bounded streaming or pagination validation in their
  adapter work.
- 236 records remain `search_only`; 134 are verified official pages needing custom adapters or
  deeper source-family work, 44 are access concerns, and 58 are conflicts.
- No company is classified as approved blocked or unsupported before the H2 decision.

## Resume point

Wait for the user's H2 decision. After approval or corrections, update statuses and evidence, run
the complete inventory audit, commit reviewed registry batches separately, and begin Phase 3 with
Ashby only if the recommended adapter order is approved.
