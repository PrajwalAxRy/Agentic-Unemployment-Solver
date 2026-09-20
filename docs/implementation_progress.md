# Implementation progress

## Current status

- Active phase: Phase 1 — Product and data contracts
- Status: Phase 0 complete; Phase 1 awaiting H1 policy approval
- Latest relevant commits: `20f0871` (search profile schema), `8aa0b69` (source/job contracts),
  `2b62a42` (recency and date coverage contracts), `17cce59` (date policy), and `71b3e97`
  (H1 review artifact)
- Pending human checkpoint: H1 — approve or correct the proposed search policy

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

## Review artifacts

- H1 search policy review: `docs/reviews/h1_search_policy_review.md`
- Recency and date coverage contract: `docs/05_recency_and_date_coverage_contract.md`

## Unresolved defects

- None.

## H1 feedback incorporated

- Generic `Software Engineer`, software-development, backend-engineering, and data-science/scientist
  titles are no longer proposed for automatic rejection.
- They enter a conditional deterministic description-review lane after recency and India-location
  checks; only substantive AI/ML work proceeds to seniority evaluation.

## Resume point

Wait for H1 approval. Then encode the approved search profile and labelled examples, run the
330-company minimum source-schema accounting check, validate, and commit the approved baseline.
