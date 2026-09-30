# JOB_Finder — orientation for AI assistants

India AI/ML job scanner. Scrapes ~150 company career sites, filters deterministically,
then asks an LLM to judge the survivors.

**Read this file first. It exists so you don't rediscover the same facts by grepping.**
Then read **`docs/decisions.md`** before proposing any change — several obvious-looking
optimisations there were measured and rejected, and re-proposing them wastes your budget
and, in one case, would break the system.

**Do not read `docs/archive/`, `docs/reviews/`, or `reports/`.** They are denied in
`.claude/settings.json`. The archive describes filters and an LLM call that no longer
exist; `reports/` is 42MB of generated output. Nothing in them is needed to work on the
code, and `latest_scan.json` is better queried with `jq` than read.

## Don't burn tokens on these — the answers are here

| Question | Answer |
|---|---|
| Is the scan parallel? | **No.** Single-threaded everywhere. `max_workers` exists in `collection.py` but is **dead code** — defaults to 1, nothing passes it, no CLI flag. |
| Are LLM calls batched? | **No.** One job per call, sequential. ~3,677 calls per full run. |
| Where are descriptions stored? | **Nowhere.** Only `description_hash` is persisted. You cannot compute description length stats from the DB. |
| Is relevance evidence stored? | **No.** Only the three-way `verdict`. The model's quote/reason for relevance is discarded. Seniority evidence *is* kept in `seniority_result_json`. |
| What does a run cost? | **$0.0020/job**, ~$7.23 for a full 3,677-job scan. Recorded per run in `state/llm_costs.jsonl`; view with `job_finder costs`. |
| Why is `conditional_pass` ~94%? | **By design, not a leak.** `filter_role` returns `CONDITIONAL_DESCRIPTION` for every surviving title — `EXPLICIT_PASS` exists in the enum but is unreachable, so nothing skips the LLM gate. See "Settled decisions". |
| Where does time go? | Unmeasured. `candidate_evaluation` has **no `seconds=` instrumentation**, unlike collection/filter. Measure before optimising. |

## Architecture: three phases, one lock

1. **`source_collection`** — `collection.py`, scrapes ~150 companies. ~3.5h.
2. **`deterministic_filter`** — same file. Also does network I/O (Workday listings say
   "N Locations", so each needs a detail fetch). Adobe alone is ~190 requests.
3. **`candidate_evaluation`** — `scan.py:process_filter_report`. HTTP description fetch +
   one merged LLM call per job. This is the slow, expensive phase.

Funnel from the 2026-09-30 run: 42,116 listings → 21,963 recent → 17,555 role → **3,677
retained** → LLM. Of 259 evaluated: 83 substantive, 23 peripheral, 153 unrelated (59%
rejected — the gate earns its keep).

## The merged LLM call (`to_change.md` 2.5)

`MergedEvaluator` makes one call per job returning three judgments: relevance
(`substantive`/`peripheral`/`unrelated`), seniority (`true`/`false`/`"uncertain"`), and
location **only** when the deterministic filter couldn't resolve it.

Each judgment carries a **verbatim evidence quote**, validated as a substring of
title+description after whitespace/case normalization. Failures trigger the retry
(~10% rate). `seniority_match` is `bool | str` — **never truthiness-check it**;
`"uncertain"` is truthy. All current consumers correctly use `is True` / `is False`.

Cache key: `description_hash` + `profile_version` + `prompt_version` + `model_policy`.
**Changing any of those re-evaluates the entire corpus** (~$7). Includes editing
`search_profile.toml` or `merged_prompt.toml`, and toggling `--seniority-only`.

## Settled decisions — do not re-propose (full reasoning in `docs/decisions.md`)

- **Description trimming: rejected.** Saves ~$4/scan, discards ~83% of text. Seniority
  signal is often back-loaded, and trimming away a quotable sentence breaks evidence
  validation, causing retries. User explicitly said skip.
- **Tightening the title filter: rejected.** Change 2.2a deliberately widened it from 11%
  to ~70-79% pass, validated at **0 false negatives** over 1,300 Amazon + 1,120 Greenhouse
  + 77 hand-written titles. The old narrow filter silently dropped real jobs
  (`ML Engineer, Prime Video Ads CX` blocked on "pr" inside *Prime*). Tightening
  re-introduces exactly those. If output volume is the complaint, tier the report instead.
- **Schema `maxLength` bounds, prompt-injection hardening, retry rework: deferred.**
  Real but latent. Measured against 259 real responses: max evidence 259 chars vs a
  500 cap, zero violations. Don't raise these again without new evidence.

## Known-latent issues (documented, not urgent)

- `merged_evaluator.py` schema dropped every `maxLength` that `seniority.py:62-68` has.
  Unbounded strings reach SQLite and markdown reports. No real response has approached it.
- One bad evidence field discards **all three** judgments, contradicting the module's own
  stated goal of per-judgment diagnosability.
- Retry resends a byte-identical request with no error feedback; no temperature/seed set.
- `is_confident_rejection` is defined and tested but **never called** — `scan.py`
  reimplements the rule inline, in a different order.
- The 20-case relevance eval set is **inert**: tests assert things about the JSON file,
  never run it against a model. No accuracy gate, unlike the seniority path's 90% gate.

## Working agreements

- **Verify before claiming.** This codebase has repeatedly punished inference from metric
  names. Read the code or query the DB; don't reason from a number's name.
- **Measure before optimising.** Three separate performance diagnoses here were wrong
  because the timing data didn't exist.
- **Never record a transient condition as per-job state.** Budget exhaustion was once
  written as `invalid_seniority_output`, which made 3,026 rows permanently unretryable.
  If a status means "we didn't get to it", it must differ from "we judged it and failed".
- Commit in focused increments with real reasoning in the message, not just what changed.
- Prefer stdlib. No `rich`/`tqdm` — `terminal.py` uses raw ANSI deliberately.

## Commands

```bash
python -m pytest -q                      # full suite, ~25s (1000+ tests)
python -m ruff format src/ tests/ && python -m ruff check src/ tests/
python -m mypy src/                      # locking.py Windows errors are pre-existing noise

python -m job_finder scan --min-request-interval 0.15 --max-concurrent-per-host 2
python -m job_finder scan --resume       # after a budget halt; checkpoint valid 24h
python -m job_finder costs               # per-day spend history
```

**Never run the test suite while a scan is live** — tests write `state/` databases and
contend for `ScanLock`.

## Layout

`src/job_finder/`: `collection.py` (phases 1-2, ~900 LOC, hottest file) · `scan.py`
(phase 3 + lifecycle) · `matching/` (LLM: `merged_evaluator`, `merged_prompt`, `service`,
`evaluator`) · `filters/` (`roles`, `locations`) · `persistence/` (SQLite + migrations) ·
`adapters/` (per-ATS scrapers, `http_client`, `connectivity`) · `checkpoint.py` (resume) ·
`cost.py` (spend ledger) · `terminal.py` (progress UI).

Config in `config/`, state in `state/` (gitignored). Secrets in `.env` (gitignored —
**never commit**). `to_change.md` is the 986-line rewrite spec; sections are cited as
"2.5", "3.2" etc. throughout the code.
