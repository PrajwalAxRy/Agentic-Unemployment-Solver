# Luna vs Sol: making Luna's judgments robust (2026-10-02 batch)

## Goal
Production uses gpt-6-luna. gpt-6.1-sol ran as a reference. Make Luna's relevance and
seniority judgments match reality, judged from the job description itself (Sol is a
strong hint, not ground truth). Missing a relevant job is worse than showing an extra one.

## Data
- Batch 2026-10-02: 3,806 candidates, 3,727 with descriptions. Both models ran in full.
- Original agreement: relevance 97.0%, seniority 98.0%. Final outcome differed on 105 jobs.
- Sets (lab/sets.json, ordinals into the 2026-10-02 batch):
  - `disagree` (192): every job where Luna and Sol differed on relevance or seniority,
    plus Luna's 5 failures. The tuning set.
  - `agree` (150): stratified sample where both agreed. Regression check.
  - `seneval` / `releval` (20 + 20): the repo's reviewed evaluation sets.
  - `holdout` (200): random, untouched until the prompt was frozen.
- Ground truth: `lab/truth.json`, 138 hand verdicts read from the descriptions, each with a
  confidence. "low" = genuinely borderline, excluded from headline metrics.
  `lab/adjudicated_cases.json` is the self-contained copy: job key, title, description,
  both models' original answers and the verdict, usable without the git-ignored data.

## Folder layout
| Path | In git | What |
|---|---|---|
| `README.md` | yes | this report |
| `run_compare.sh`, `profiles/` | yes | unattended discovery + Luna/Sol run (no secrets in profiles) |
| `lab/lab.py` | yes | harness: `build`, `run` (prompt x model x set x reps), `score` |
| `lab/view.py`, `lab/adjudicate.py`, `lab/compare.py` | yes | read cases, record verdicts, compare two runs |
| `lab/prompts/v0..v4.toml` | yes | every prompt variant tested (v4 = shipped 1.2.0) |
| `lab/truth.json`, `lab/evaltruth.json`, `lab/sets.json`, `lab/groups.json` | yes | verdicts and case sets |
| `lab/adjudicated_cases.json` | yes | self-contained adjudicated cases |
| `runs/<date>/` | no | run databases, logs, reports, cost ledgers (~300 MB) |
| `lab/cases.json`, `lab/results/` | no | frozen inputs and raw per-call replies (~45 MB) |
| `scratch/` | no | one-off probes and run logs |

## Rules used for the verdicts (please review; these are policy choices)
1. An engineering role whose duties, or whose team's stated engineering work, explicitly
   include building/deploying/integrating ML or AI features is at least "peripheral"
   (visible), even if that is only part of the job.
2. Quota-carrying sales, account, consulting-leadership, delivery and operations
   management are "unrelated" even when the product is AI. Technical customer/solutions
   engineering for AI products and managers of AI engineering teams are "peripheral".
3. Generic job-family template text (Barclays' "Collaboration with data scientist to
   build and deploy machine learning models", which also appears on Pega, SRE and C++
   postings) is not evidence. Judge the role-specific part.
4. Business/credit/collections analytics with scorecards or statistical models is
   "unrelated" unless machine learning is named.
5. A title naming AI/ML/GenAI/LLM/data science counts, unless the duties show it is
   misleading (e.g. a "Data Scientist" doing only BI reporting).
6. Hardware design/verification for AI accelerators is "peripheral" (as the prompt
   already said).

## Findings
1. Luna is noisy on borderline jobs. Across 3 reruns of the 192 disagreements, Luna
   changed its relevance answer on 49 (26%), Sol on 12 (6%). Luna's flips were almost all
   substantive <-> unrelated: it skipped the "peripheral" middle category.
2. Sol is not a reliable ground truth at the boundary. On 72 medium/high-confidence
   verdicts, Sol missed 9 relevant jobs and let 13 irrelevant ones through. It
   under-counts engineering roles with AI duties and over-trusts template text and AI
   sales/consulting.
3. Sampling controls do not help. reasoning_effort low/high and temperature=0+seed are all
   accepted by the gateway and none reduced instability (51-55/192 unstable vs 49).
   Evidence-before-verdict schema ordering also made no difference. Prompt clarity was the
   only lever that worked.
4. Luna's remaining hard failures were the evidence validator rejecting correct quotes:
   a U+2011 non-breaking hyphen copied as "-", or a trailing period added where the source
   line ends at a bullet. The identical retry failed the same way.

## Iterations (72 medium/high-confidence disagreements; "single call" = expected per-call rate)
| Variant | Gate missed (vote / single) | Gate extra (vote / single) | You-see missed / extra | Relevance unstable |
|---|---|---|---|---|
| v0 current prompt | 14 / 14.0 | 22 / 19.7 | 6 / 13 | 49/192 |
| v0 reasoning low | 12 / 11.3 | 17 / 17.7 | 6 / 12 | 55 |
| v0 reasoning high | 11 / 11.0 | 25 / 23.7 | 5 / 15 | 53 |
| v0 temperature 0 | - / 12.3 | - / 19.0 | - | 51 |
| v0 evidence-first | 13 / 11.7 | 20 / 20.3 | 6 / 13 | 50 |
| v1 inclusive rules | 0 / 0.7 | 23 / 22.7 | 0 / 13 | 48 |
| v2 + patterns (f)-(i) | 4 / 3.3 | 7 / 8.3 | 2 / 1 | 32 |
| v3 + fixes | 0 / 1.0 | 6 / 7.0 | 0 / 3 | 37 |
| **v4 (shipped as 1.2.0)** | **1 / 0.3** | **5 / 6.0** | **1 / 1** | **27** |
| Sol | 9 / 8.0 | 13 / 12.5 | 6 / 10 | 12 |

Reviewed sets: v0 seniority 20/20, relevance 18/20. v4 seniority 20/20, relevance 20/20.
Agreed-set regression (150 jobs, vs verdict or consensus): v0 1 missed / 7 extra;
v4 1 missed (low confidence) / 3 extra (2 low confidence); unstable 11 -> 9.

## Holdout (200 random jobs, never used for tuning)
| | Gate errors (vote) | Single-call missed / extra per 197 jobs |
|---|---|---|
| v0 | 2 extra, 1 missed | 1.00 / 1.67 |
| Sol (original run) | 1 extra, 1 missed | - |
| v3 | 1 extra | 0.00 / 1.33 |
| **v4** | **0** | **0.33 / 0.67** |
Caveat: holdout truth is mostly the two models' consensus (they agreed on all of these),
plus 7 hand verdicts where a variant disagreed. It shows v4 does not break easy cases.
v4 crosses the relevant/unrelated line between reruns on 4/200 holdout jobs (v0: 1).

## Cost (Luna list price, from recorded usage)
v0 $0.00026/job, v4 $0.00030/job (prompt ~750 tokens longer, mostly cached),
about $1.11 per full 3,727-job run. Sol: $0.00358/job, about $13.33 per run.

## Changes in the repo
- `config/merged_prompt.toml` -> 1.2.0 (= lab/prompts/v4.toml), including the 1.1.0
  edits it was built on. Changing it invalidates cached judgments: run
  force_reevaluate or a fresh scan.
- `src/job_finder/matching/merged_prompt.py`: evidence check folds typographic variants
  (hyphens/dashes, curly quotes, non-breaking/zero-width spaces) and ignores a leading
  bullet / trailing period. Wording and interior punctuation must still match, and a lone
  "." is now rejected (the old check accepted it). Tests in
  tests/matching/test_merged_prompt.py fail on the old code. On probe replies: 27/30 valid
  (was 14/30); the 3 still rejected are a genuine paraphrase.
- Committed earlier: 552b684 (cost/caching/reasoning token capture), 1294306 (report crash
  on quoteless merged decisions).

## Not done / next steps
1. Seniority "uncertain": 877 jobs where both models agree on uncertain. Out of scope here
   as agreed. The 65 seniority disagreements on unrelated jobs were not adjudicated.
2. Location was never exercised: the deterministic filter resolved every job in this batch.
3. Luna still flips on ~14% of hard cases (27/192). A cheap option if it matters: a second
   call only when the first answer is "unrelated" with a non-empty AI mention, showing the
   job if either call says relevant. Not tested.
4. Retry still resends an identical request with no feedback (known latent issue). After
   the validator fix, retries are ~1% of calls, so this is low priority.
5. Validate v4 on a fresh batch (new descriptions) before trusting the numbers fully.
6. adjudicated_cases.json could become a runnable relevance evaluation set with an accuracy
   gate, like the seniority path has.

## Reproduce
From the repository root (needs the git-ignored runs/ and lab/results/ data locally):

    uv run --locked python experiments/llm_compare/lab/lab.py score \
      --tags luna_base,luna_v4,sol_base --set disagree \
      --truth experiments/llm_compare/lab/truth.json,experiments/llm_compare/lab/evaltruth.json

Raw replies for every call (v1 onward) are in lab/results/*.jsonl. To test a new prompt on
the same cases: `lab.py run --tag NAME --prompt PATH --set disagree --reps 3`, then score.
Never run the test suite while a comparison run is live (shared state/ and ScanLock).
