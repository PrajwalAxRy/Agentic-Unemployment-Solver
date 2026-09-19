# Job Finder

A manually triggered system for discovering recent AI and machine-learning job postings from the
canonical company registry.

Implementation follows the phased execution plan in
[`docs/03_job_posting_discovery_phased_execution_plan.md`](docs/03_job_posting_discovery_phased_execution_plan.md).

## Development status

The implementation is being built phase by phase. The only user command available during the
repository-foundation phase is:

```powershell
uv run --locked job-finder --version
```

See [`docs/development.md`](docs/development.md) for environment setup and validation instructions,
and [`docs/implementation_progress.md`](docs/implementation_progress.md) for the current phase and
checkpoint state.

## Data boundaries

- `data/company_seed.csv` is the canonical first-release list of all 330 companies.
- The workbook named in `data/README.md` is immutable provenance material, not a runtime input.
- Local state, generated reports, cached responses, diagnostics, browser captures, and secrets are
  excluded from Git.
