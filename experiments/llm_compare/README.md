# Luna vs Sol: making Luna's judgments robust (2026-10-02 batch)

> **Current state (2026-10-06).** Production runs merged prompt 2.0.0 (lab prompt v10,
> schema 2: `core_ai`/`ai_involved`/`uncertain`/`not_ai`, `work_summary`, `location_fit`)
> at Luna `high` reasoning effort. It was chosen on a blind 1,000-job benchmark scored
> against the user's written policy (`policy/policy_v1.md`); see
> `bench_2026-10-05_report.md`. The lab-only contract in `lab/v2.py` is now production's
> (`src/job_finder/matching/merged_prompt.py`); `lab/smoke_production.py` makes one real
> call with the production settings. The history below predates that benchmark.

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
| `run_full_lab.sh` | yes | discovery + Luna pipeline check + harness reruns (Luna x4, Sol x3, seniority variant x2) in one command |
| `lab/costs.py`, `lab/compare_full.py` | yes | price harness runs; whole-batch shown/flip counts |
| `lab/prompts/v8s.toml` | yes | experiment only: 1.3.0 with a title-decides seniority rule when no years are stated (reviewed seniority set 19/20: it turns a "Principal" with no years from uncertain to false, by design) |
| `lab/lab.py` | yes | harness: `build`, `run` (prompt x model x set x reps), `score` |
| `lab/view.py`, `lab/adjudicate.py`, `lab/compare.py` | yes | read cases, record verdicts, compare two runs |
| `lab/view_runs.py`, `lab/view_blind.py` | yes | print cases with any runs' answers / with no answers |
| `lab/strategies.py`, `lab/score_consensus.py` | yes | simulate call strategies; flips vs two-model consensus |
| `lab/fresh_sets.py`, `lab/fresh_validation_sets.py`, `lab/location_probe.py` | yes | sets for another batch (`LAB_BATCH`); location probe |
| `lab/prompts/v0..v8.toml` | yes | every prompt variant tested (v4 = 1.2.0, v8 = shipped 1.3.0) |
| `lab/truth.json`, `lab/evaltruth.json`, `lab/sets.json`, `lab/groups.json` | yes | verdicts and case sets |
| `lab/truth_2026-10-03.json`, `lab/sets_2026-10-03.json`, `lab/fresh_*.json` | yes | the same for the 2026-10-03 batch |
| `lab/adjudicated_cases.json` | yes | self-contained adjudicated cases |
| `runs/<date>/` | no | run databases, logs, reports, cost ledgers (~300 MB) |
| `lab/cases*.json`, `lab/results*/` | no | frozen inputs and raw per-call replies (~45 MB per batch) |
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

## Round 2 (2026-10-03)

### Sol on the new prompt (fair head-to-head)
Sol had only run on 1.1.0. On 1.2.0, 72 medium/high-confidence disagreements, per call:
| | Missed | Extra | Unstable reruns |
|---|---|---|---|
| Sol 1.1.0 | 8.0 | 12.5 | 12/192 |
| Sol 1.2.0 | 0.0 | 3.0 | 12/192 |
| Luna 1.1.0 | 14.0 | 19.7 | 49/192 |
| Luna 1.2.0 | 0.3 | 6.0 | 27/192 |
The prompt fixed most of both models' errors; Sol stays somewhat better at ~12x the cost.
On the holdout Sol 1.2.0 "missed" 3: one is a Sol error (#2356, (d) misapplied to a role
that builds AI models), two are borderline.

### Instability: what it costs and the fix (`lab/strategies.py`)
Judgments are cached by exact request, so a job does not flip from day to day; instability
decides which answer is frozen the first time. Simulated from recorded reruns
(relevance gate errors, per job set):
| Strategy | Hard cases missed/extra | Holdout missed/extra | Cost/job |
|---|---|---|---|
| 1 Luna call (today) | 0.3 / 9.0 | 0.3 / 0.7 | $0.00030 |
| 2 Luna calls, 3rd only if they disagree | 0.0 / 8.0 | 0.0 / 0.0 | ~$0.00061 |
| 2 Luna, show if either says relevant | 0.0 / 12.0 | 0.0 / 1.3 | $0.00060 |
| 2 Luna, Sol breaks ties | 0.0 / 6.7 | 0.7 / 0.0 | ~$0.0007-0.0009 |
| 1 Sol call | 0.0 / 6.3 | 3.0 / 0.0 | $0.00360 |
Implemented as `JOB_FINDER_LLM_SECOND_OPINION=true` (off by default): the second row.

### The review list was mostly not an LLM problem
Of 1,060 review items on 2026-10-02: 816 Bank of America `detail_location_unavailable`,
109 seniority uncertain, 79 no description, 46 other location reviews, 5 failures.
1. **Bank of America** (816): Workday's detail payload says `/Lateral-US/job/...`, the
   config says `lateral-us`; a case-sensitive check failed every detail fetch. Fixed in
   `adapters/workday.py`; a live job now resolves to 5 US cities and is rejected by the
   location filter. Also ~25 minutes of failed fetches per scan.
2. **No description** (79; 69 from Porter whose postings have an empty JD): now judged from
   the title with an explicit placeholder; all 79 titles were non-AI.
3. **Location reviews**: to_change.md 2.4 (decided) says the model decides India
   eligibility for unresolved locations, but REVIEW rows never entered evaluation, so the
   location judgment was dead code. They are admitted now. Probe on the 51 real rows
   (`lab/location_probe.py`): 48 unrelated (drop out of review), 2 relevant and eligible
   (surface as matches, e.g. "Data Scientist, Pharma Domain"), 1 relevant with unknown
   location (review). Luna and Sol agreed on every relevant row.
4. **Seniority uncertain** (98 relevant jobs both models call uncertain): every sampled
   posting states no years at all; most carry VP/AVP/Director/Principal/Lead/Senior
   titles (Barclays alone: 38). "Uncertain" is correct under the current rule that a title
   never decides. Shrinking it needs a policy decision (e.g. no stated years + senior
   title -> not eligible), left to the user.

## Round 3 (2026-10-04): the fresh batch, prompt 1.3.0

### Did 1.2.0 hold up on new data? Partly.
Both models ran 1.2.0 over the whole 2026-10-03 batch (3,662 jobs, one call each). They
disagreed on the relevance gate for 114 jobs: 90 where only Luna passed, 24 where only Sol
passed. Hand verdicts (`lab/truth_2026-10-03.json`, 49 jobs): all 24 Sol-only passes and a
random 25 of the Luna-only passes.
- Sol-only (possible Luna misses): Sol right on 15, Luna on 9; 8 of Sol's are medium
  confidence (e.g. "Staff AI Engineer", a title listing GenAI, RAG/embeddings in required
  qualifications, an EM of an "AI-first trust stack").
- Luna-only (possible extras): Sol right on 17, Luna on 8. Luna's extras were mostly
  systematic, not noise: they repeated on 3 of 3 reruns (Barclays job-family templates,
  "potentially leveraging AI/ML", a data-center technician racking "ML platforms",
  AI-driven verification tooling).
- So the second opinion alone could not fix them: it only removes answers that flip.

### Prompt iterations (lab/prompts/v5..v8; per call, missed / extra)
| Set | Luna 1.2.0 | v5 | v7 | **v8 = 1.3.0** | Sol 1.2.0 |
|---|---|---|---|---|---|
| Fresh hard cases, med/high (18; in-sample) | 3.7 / 8.0 | 1.7 / 7.0 | 1.3 / 2.3 | **1.7 / 1.3** | 2.0 / 1.0 |
| ...same, what you see (match or review), majority of reruns | 1 / 6 | 1 / 3 | 0 / 0 | **0 / 0** | 1 / 1 |
| Original 72 hard cases (2026-10-02) | 0.3 / 6.0 | 1.0 / 7.7 | 1.0 / 4.7 | **0.3 / 5.0** | 0.0 / 3.0 |
| 300 random fresh jobs, flips vs consensus | 1 / 2 | - | - | **1 / 0** | (reference) |
| 2026-10-02 holdout (196), vs consensus | 0.0 / 0.7 | 0.5 / 2.0 | 1.0 / 2.5 | **0.0 / 4.0** | 2.0 / 0.0 |
| Reviewed relevance / seniority sets | 20/20, 20/20 | 20/20, 20/20 | - | **20/20, 20/20** | - |
The holdout extras under v8 are mostly senior roles (seniority false), so they never reach
the report; 1.5 of the 4.0 are visible. v5 alone (required-qualification rule) regressed the old
set (KLA DevOps "AI agents for DevOps" and PANW "LLM debug tools" passed); v7 fixed that by
naming those as pattern (d).

What changed (all in the relevance section):
1. Required qualifications that demand building with AI/ML (RAG, embeddings, fine-tuning,
   AI agents, integrating ML/GenAI into production software) count for peripheral (ii);
   using AI tools or applying AI to the team's own dev/DevOps/test/debug workflow does not.
2. The title rule wins over (f)/(i): "AI Engineer", or a title listing GenAI, is at least
   peripheral.
3. (f) applies even when the template's purpose statement names ML (Barclays).
4. (i) covers hedged mentions ("potentially leveraging AI/ML", "where appropriate") and
   AI/ML as one example of the equipment a technician installs.
5. (d) names AI agents for DevOps, LLM-based debug tools, AI-driven coverage analysis.

Whole 2026-10-03 batch, one call each (`lab/compare_full.py`): jobs shown (relevant and
seniority not false) 345 with 1.2.0, 329 with 1.3.0, 319 with Sol. 1.3.0 stops showing 33
and newly shows 17. Sol agrees with 23 of the 33 drops; most of the rest are Barclays
template rows (Sol passes "Collaboration with data scientist to build and deploy machine
learning models", which rule 3 above treats as template) or hedged "you could later use
ML" postings. The gains are mostly titles/required qualifications (Visa, Adobe). Shown-set
disagreement with Sol falls from 62 jobs to 50; part of what remains is rerun noise.

Validation caveats: the fresh hard cases were used for tuning (in-sample). The independent
checks are the original 72, the 2026-10-02 holdout and agreed sets, and 300 random fresh
jobs. On the 65 Luna-only passes that were never hand-judged, v8 rejects 46% of calls
(Sol was right on 68% of the sampled Luna-only passes), but those were not adjudicated.

### Policy questions surfaced (not decided here)
- **Annotation roles.** Amazon "ML Data Associate" postings (~7 per batch, all
  early-career) are non-technical labelling. 1.2.0 Luna and Sol both pass them. v5-v7
  excluded them; 1.3.0 keeps the 1.2.0 behaviour (only their managers are pattern (e)),
  though Luna 1.3.0 still drops one occasionally because peripheral (i) says "technical
  role".
- **Consulting architects who design AI solutions for clients** (Salesforce technical
  consulting managers): judged both ways; they are all senior, so they never show.

## Round 4 (2026-10-04): full lab run, Luna x4 vs Sol x3, blind adjudication

`run_full_lab.sh` on a fresh batch (3,634 jobs): discovery with the Bank of America and
REVIEW-admission fixes, Luna 1.3.0 + second opinion through the real pipeline, and harness
reruns (Luna x4, Sol x3, seniority variant x2). Costs: Luna x4 $4.28, Sol x3 $42.10,
variant $2.22, pipeline $1.94 (7,366 calls, 2.03 per job). Five pipeline halts were gateway
failures, each resumed automatically.

Pipeline result: review list 106 (100 seniority uncertain, 5 evidence failures, 1 location
uncertain), down from 976; 0 deterministic filter reviews (Bank of America: 880 detail
fetches, 0 failures, all US). 226 matches. 42 unresolved locations went to the model.

Instability: Luna changed its gate answer across 4 calls on 137 jobs (3.8%), Sol across 3
calls on 46 (1.3%). The majorities disagreed on 111 jobs (91 Luna-only pass, 20 Sol-only).
All 111 were judged blind (`lab/blind_verdicts_2026-10-04.txt`, no model answers shown,
shuffled order), then unblinded (`lab/unblind.py`): 63 of 111 are genuinely borderline
("low"). On the 48 confident ones, per call (`analyze_reps.py --only-judged`):
| | Gate missed | Gate extra |
|---|---|---|
| 1 Luna call | 2.0 | 15.0 |
| 2 Luna + tie-break (second opinion) | 1.5 | 16.5 |
| 1 Sol call | 16.3 | 5.3 |
Sol 1.3.0 misses roles that BUILD AI systems for internal engineers (Adobe AI agent
platform, Amazon LLM remediation agents, Cadence LLM fine-tuning, Safe "Engineering
Productivity (AI)"), each time citing the (d) "AI-assisted SDLC" exclusion; 1.3.0 widened
(d) and Sol over-applies it. Luna's extras are consulting/strategy roles, generic SWE
postings with AI tooling, and template text, often unstable across calls. The second
opinion barely helps because both models' errors repeat.

## Not done / next steps
1. Seniority policy for "no years stated" (above) is a user decision.
2. The 65 seniority disagreements on unrelated jobs were not adjudicated.
3. Retry still resends an identical request with no feedback (known latent issue). After
   the validator fix, retries are ~1% of calls, so this is low priority.
4. adjudicated_cases.json could become a runnable relevance evaluation set with an accuracy
   gate, like the seniority path has.

## Reproduce
From the repository root (needs the git-ignored runs/ and lab/results/ data locally):

    uv run --locked python experiments/llm_compare/lab/lab.py score \
      --tags luna_base,luna_v4,sol_base --set disagree \
      --truth experiments/llm_compare/lab/truth.json,experiments/llm_compare/lab/evaltruth.json

Raw replies for every call (v1 onward) are in lab/results/*.jsonl. To test a new prompt on
the same cases: `lab.py run --tag NAME --prompt PATH --set disagree --reps 3`, then score.
Never run the test suite while a comparison run is live (shared state/ and ScanLock).
