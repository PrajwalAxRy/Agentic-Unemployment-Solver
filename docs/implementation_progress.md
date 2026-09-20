# Implementation progress

## Current status

- Active phase: Phase 2 — Company source inventory
- Status: Phases 0 and 1 complete; H1 approved; Phase 2 in progress
- Latest relevant commits: `20f0871` (search profile schema), `8aa0b69` (source/job contracts),
  `2b62a42` (recency and date coverage contracts), `17cce59` (date policy), and `71b3e97`
  (H1 review artifact), with generic-title feedback in `74bb710` and mixed-remote feedback in
  `d47791a`; approved profile encoded in `b63afc6` and seed audit added in `0fbff07`
- Pending human checkpoint: H2 — approve source proposals and unresolved coverage decisions

## Completed gates

- Required repository instructions and design documents read in full.
- Canonical seed verified: 330 rows, 330 unique IDs, 330 unique names, and 330 unique ranks.
- Priority counts verified: 96 P1, 106 P2, and 128 P3.
- Provenance workbook located and verified against the documented SHA-256 checksum.
- Pre-existing untracked directories recorded and preserved: `.artifact_build/`, `.codex_tmp/`, and
  `outputs/`.
- Supported runtime selected: CPython 3.12 with `uv` dependency management.
- Phase 0 package, directory, configuration, ignore, and dependency structure created.
- Locked clean-checkout install succeeded with CPython 3.12.7.
- Repository validation passed: Ruff format, Ruff lint, strict mypy, and 4 pytest tests.
- `job-finder --version` and `python -m job_finder --version` both report `0.1.0`.
- Temporary generated report and database were ignored successfully and removed after the check.
- Search-profile schema version 1 validates role, location, ten-day, date-uncertainty, and seniority
  boundaries and produces deterministic content hashes.
- Company-source, normalized-job, adapter-result, and diagnostic schema version 1 implemented.
- Rolling-window and full-registry H5 date-measurement contracts implemented.
- Repository validation passed after Phase 1 contract work: Ruff format, Ruff lint, strict mypy,
  and 40 pytest tests.
- H1 approved by the user on 2026-09-20.
- Approved search profile `1.0.0` and 49 labelled policy examples encoded and validated.
- All 330 companies passed the minimum source-schema audit with zero invalid configurations.
- Repository validation passed after H1 encoding: Ruff format, Ruff lint, strict mypy, and 48
  pytest tests.

## Review artifacts

- H1 search policy review: `docs/reviews/h1_search_policy_review.md`
- Recency and date coverage contract: `docs/05_recency_and_date_coverage_contract.md`
- Phase 1 company schema audit: `docs/reviews/phase1_company_schema_audit.md`

## Unresolved defects

- None.

## H1 feedback incorporated

- Generic `Software Engineer`, software-development, backend-engineering, and data-science/scientist
  titles are no longer proposed for automatic rejection.
- They enter a conditional deterministic description-review lane after recency and India-location
  checks; only substantive AI/ML work proceeds to seniority evaluation.
- `Singapore or Remote` is accepted when remote is a separate unqualified option, unless other
  evidence explicitly restricts remote work to a non-India geography. Bare `Remote` remains a
  location-review case.

## Resume point

Implement the Phase 2 registry, validator, discovery proposal importer, and coverage reporting;
research all 330 sources; then stop at H2 with only unresolved proposals and policy decisions.
