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
uv run --locked job-finder evaluate          # resume saved evaluation progress
uv run --locked job-finder force_reevaluate  # evaluate the entire saved batch again
uv run --locked job-finder costs             # spending, including discarded attempts
```

**Expect hours.** The pipeline is single-threaded. The historical full run spent roughly 3.5h
collecting sources and retained 3,677 jobs, costing an estimated $7 at its configured rates.
Discovery now freezes full descriptions before evaluation; exact cached judgments avoid repeat
LLM calls. Forced reevaluation bypasses that cache and can incur the full cost again.

Each IST date has one `state/logs/scan-YYYY-MM-DD.log` and one dated JSON/Markdown report pair,
plus `reports/latest_scan.*`. A fresh scan replaces that day's artifacts and saved batch.
`evaluate` resumes the current attempt; `scan --resume` is its compatibility alias. New evaluation
invocations are allowed only before midnight IST ending the scan's admission date.

`state/jobs.sqlite3` stores durable identity, the frozen batch, progress and request usage;
`state/llm_costs.jsonl` preserves spending exports and discard markers. Fatal discovery failure
requires a fresh scan; interrupted evaluation can resume. Old JSON checkpoints are retired,
so begin the upgrade with a fresh scan. It does not schedule itself or send notifications.

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
