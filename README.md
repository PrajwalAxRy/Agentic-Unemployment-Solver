# Job Finder

A manually triggered scanner for recent AI and machine-learning job postings at ~150 Indian
company career sites.

It scrapes public job boards, filters deterministically on recency, location and title, then sends
each survivor to a single LLM call that judges AI/ML relevance, seniority, and — when the
deterministic filter could not resolve it — India eligibility.

## Run a manual scan

After configuring the local provider variables described in
[`docs/06_llm_provider_configuration.md`](docs/06_llm_provider_configuration.md):

```powershell
uv run --locked job-finder scan
uv run --locked job-finder scan --resume   # continue a run that halted on budget
uv run --locked job-finder costs           # per-day spend history
```

**Expect hours.** The pipeline is single-threaded: roughly 3.5h of source collection, then one HTTP
fetch and one LLM call per retained job, sequentially. A full scan costs about $7.

Outputs are `reports/latest_scan.md` (for a person), `reports/latest_scan.json` (complete
accounting), `state/jobs.sqlite3` (durable identity and evaluation state), and
`state/llm_costs.jsonl` (spend ledger). It does not schedule itself or send notifications.

## Where to look

| | |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | How the system works today — architecture, measured numbers, known traps. **Start here.** |
| [`docs/decisions.md`](docs/decisions.md) | What was decided and why. Read before proposing a change; several obvious-looking optimisations are settled and were rejected for recorded reasons. |
| [`docs/07_scan_runbook.md`](docs/07_scan_runbook.md) | Operating a scan, reading the report, recovering from a budget halt. |
| [`docs/04_product_decisions.md`](docs/04_product_decisions.md) | Approved search behaviour and the seniority boundary table. |
| [`docs/development.md`](docs/development.md) | Environment setup and the validation command. |
| [`docs/archive/`](docs/archive/) | Pre-rewrite build history. Historical — it describes filters and an LLM call that no longer exist. |

## Data boundaries

- `data/company_seed.csv` is the canonical seed of all 330 companies. ~150 are enabled; the
  180-company backlog was descoped (`docs/decisions.md` D9).
- The workbook named in `data/README.md` is immutable provenance material, not a runtime input.
- Local state, generated reports, cached responses, diagnostics, browser captures, and secrets are
  excluded from Git.
