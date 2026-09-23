# Job Finder

A manually triggered system for discovering recent AI and machine-learning job postings from the
canonical company registry.

Implementation follows the phased execution plan in
[`docs/03_job_posting_discovery_phased_execution_plan.md`](docs/03_job_posting_discovery_phased_execution_plan.md).

## Run a manual scan

After configuring the local provider variables described in
[`docs/06_llm_provider_configuration.md`](docs/06_llm_provider_configuration.md), run:

```powershell
uv run --locked job-finder scan
```

The command writes an ignored human-readable report to `reports/latest_scan.md`, a complete
machine-readable report to `reports/latest_scan.json`, and durable duplicate/evaluation state to
`state/jobs.sqlite3`. It does not schedule itself or send notifications.

See [`docs/development.md`](docs/development.md) for environment setup and validation instructions,
[`docs/07_scan_runbook.md`](docs/07_scan_runbook.md) for operating and troubleshooting the scan,
and [`docs/implementation_progress.md`](docs/implementation_progress.md) for the current phase and
checkpoint state.

## Data boundaries

- `data/company_seed.csv` is the canonical first-release list of all 330 companies.
- The workbook named in `data/README.md` is immutable provenance material, not a runtime input.
- Local state, generated reports, cached responses, diagnostics, browser captures, and secrets are
  excluded from Git.
