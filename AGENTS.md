# Job Finder repository instructions

> **The original build is finished.** This file now covers only the standing rules that
> outlived it: source-data handling, safety, and Git discipline. For how the system
> actually works, read `CLAUDE.md`.

## Read before changing anything

- **`CLAUDE.md`** — current architecture, measured numbers, and the traps this codebase sets.
- **`docs/decisions.md`** — what was decided and rejected, with reasons. Read before
  proposing an optimisation; several obvious-looking ones are settled and were rejected
  for recorded reasons.
- `docs/04_product_decisions.md` — approved search behaviour and the seniority boundary table.
- `docs/05_recency_and_date_coverage_contract.md` — the recency window contract.
- `docs/07_scan_runbook.md` — running a scan and interpreting the output.
- `docs/archive/` — the pre-rewrite build history. **Historical, not current.** It
  describes a narrow title filter and a seniority-only LLM call, both replaced. Read it
  for the H0–H11 checkpoint definitions and source-activation forensics, never for how
  the pipeline behaves today.
- Inspect Git status before editing. Preserve pre-existing user files and unrelated untracked content.

## Execution behavior

- Continue autonomously through routine implementation, debugging, testing, and documentation.
- Stop when continuation needs authority the user has not granted. Never infer approval from silence.
- Record any decision that closes off an alternative in `docs/decisions.md`, with the reason.
  A conclusion without its reasoning gets re-litigated.

## Current scope

- Manually triggered. No scheduler, no notifications.
- ~150 enabled sources. The 180-company backlog was descoped by the user.
- Rolling ten-day listing window (`docs/05_recency_and_date_coverage_contract.md`).
- Deterministic location and title filters run before description retrieval; **location
  before title**. Surviving titles reach one merged LLM call that judges relevance,
  seniority, and (only when unresolved) location.

## Source-data rules

- `data/company_seed.csv` is the canonical first-release company list.
- The Excel workbook recorded in `data/README.md` is provenance material. Treat it as immutable: do not move, rename, overwrite, reformat, or delete it.
- Treat `careers_url_hint` as discovery evidence, not an approved official source. Verify a source before enabling it.
- Preserve all 330 seed companies in accounting reports. Any unsupported, blocked, or disabled company needs an explicit reason and the required user decision.
- Do not hand-edit generated company IDs. If source data changes, use a documented deterministic regeneration process and review the diff.

## Safety and external access

- Use public job sources only. Do not bypass authentication, CAPTCHA, rate limits, robots controls, or other access restrictions.
- Never ask the user to paste API keys, cookies, session tokens, or passwords into chat.
- Store secrets only in ignored local environment files. Keep placeholders in `.env.example`.
- Do not print, log, stage, or commit secrets, cookies, full browser sessions, local databases, cached responses, generated reports, or temporary diagnostics.
- Use bounded requests, truthful client identification, timeouts, retries, backoff, and conservative request volume.
- Use disposable test state for destructive tests. Never run the test suite while a scan is live: tests write `state/` databases and contend for `ScanLock`.

## Engineering and Git

- Python 3.12 (pinned in `pyproject.toml`). Run `scripts/validate.py`, or ruff format, ruff check, mypy, and pytest in that order.
- Prefer standard-library or established dependencies with a clear need. Keep source-specific behavior inside adapters or configuration.
- Add regression evidence before fixing a confirmed parser or filtering defect.
- Run focused tests after each change and the repository validation command before each commit once it exists.
- Commit every meaningful completed change separately with a focused message. Do not accumulate an entire phase into one commit.
- Before committing, inspect the staged diff and exclude secrets, generated state, temporary files, the provenance workbook, and unrelated user content.
- Do not commit knowingly broken work merely to reach a checkpoint.
