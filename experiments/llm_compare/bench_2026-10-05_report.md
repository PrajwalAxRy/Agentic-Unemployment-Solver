# Benchmark report: prompts 1.3.0 / 1.4.0 / v10, 1,000 labelled jobs (2026-10-05 batch)

Run: `run_bench_2026-10-05.sh`, finished 2026-10-06 14:18, no provider errors. Truth:
`lab/truth_bench_2026-10-05.json` (policy v1.2; Claude's blind labels plus the user's
review). Full tables: `runs/2026-10-05/bench_summary.md` (git-ignored). Total cost: $5.43.

Numbers below are **per call** (what production sees with one call per job), Luna default
effort, review-changed jobs excluded. "Relevance" = relevance judgment alone; "shown" = end
to end (relevance, seniority and location together). The sealed test half was scored
once, counts only; no test-half job was looked at.

| | tune: relevance missed / extra | tune: shown missed / extra | test: relevance missed / extra | test: shown missed / extra | seniority wrongly opened (tune / test) |
|---|---|---|---|---|---|
| 1.3.0 (production) | 5.3 / 8.3 | 2.7 / 12.3 | 6.3 / 4.7 | 1.7 / 5.0 | 9.0 / 4.0 |
| 1.4.0 | 1.0 / 50.7 | 0.0 / 19.7 | 2.0 / 38.7 | 1.0 / 14.3 | 2.7 / 1.0 |
| **v10** | **0.7 / 43.3** | **0.0 / 16.0** | **1.0 / 28.7** | **1.0 / 8.7** | **2.3 / 0.3** |

Tune half: 93 relevant jobs, 35 shown end to end. Test half: 78 relevant, 27 shown.

## Findings

1. **v10 is the best prompt.** It nearly removes missed jobs: relevance misses fall from
   5-6 to about 1 per half, and end-to-end misses on the tuning half from 2.7 to 0. The
   price is extra jobs: about 16 extra shown jobs on the tuning half (vs 12 for 1.3.0) and
   9 on the test half (vs 5). 1.4.0 is close behind but shows more extras on both halves.
2. **Most of v10's extras are tagged, not plain matches.** Of 42 tuning-half relevance
   extras (majority vote), 24 are "uncertain" and 18 "ai_involved"; seniority hides 31 of
   them, leaving 11 visible.
3. **Seniority improves a lot.** 1.3.0 opens 9 / 4 closed jobs to the candidate (its rule
   "title seniority alone never decides"); v10 opens 2.3 / 0.3. Nothing open was wrongly
   closed by any prompt.
4. **xhigh effort does not help.** Same misses, similar or more extras (v10 test: 14.5
   shown extras at xhigh vs 8.7 at default), 1.8x the cost. Keep default effort.
5. **1.3.0's misses** are the policy's newer grey areas: analysts who deploy models while
   requiring LLM/RAG building (19), product owners and data engineers with a real AI part
   (2002, 2891), econometrics and quant modelling (555, 1681, 900 consulting).
6. **Stability:** v10 flips visibility between calls on 11 of 479 tuning jobs (1.3.0: 4).

## v10's visible extras on the tuning half (11, majority vote)

- **Using AI tools mistaken for building or testing AI**: AI-assisted UAT test generation
  (1854), prompt-engineering test scenarios (2822), "use AI to solve business problems"
  for efficiency (2082). The new "testing AI systems" rule is being read as "testing
  with AI".
- **Analysts with "models" in their duties**: prioritisation models (3357), analytics /
  data-science domain experience (1418). These are close to the user's review answers that
  made forecasting and decision-model analysts AI-involved (R1415, R1674, R1693); the
  labels were made under v1.1 and may now be wrong rather than the prompt.
- **AI only as context or preference**: AI-driven decisioning in the platform (3414),
  ML exposure preferred (2617), team-level modelling text (2779), algorithmic output
  integrated via REST (1273), agent-integration template text (823), an apprentice
  supporting AI-enabled tools (1392).

## Label consistency caveat

The blind labels were made under policy v1.1. v1.2 widened AI-involved (analysts building
forecasting or decision models, AI titles alone, testing or securing AI, platforms running
ML), but only the 103 reviewed jobs were relabelled. Unreviewed jobs those rules now cover
are still labelled by v1.1, so some "extras" (3357, 1418 above) may be label errors under
v1.2. A rule-driven relabel of the unreviewed labels, made without looking at model
answers for the test half, should precede tuning.

## Addendum 2026-10-06: v1.2 re-check of unreviewed labels

All 1,000 labels were checked against the v1.2 rules without new model calls. Candidates
were picked by rule from the job text alone (AI title; forecasting, decision or predictive
models; testing, validating or securing AI; platforms for ML; prompts): 139 unreviewed
"hide" labels, of which 24 changed (source `recheck_v1.2` in the truth file, with the
reason). 19 became uncertain (integrating someone else's AI, preferred AI related to what
the role builds, AI-oversight duties) and 5 AI-involved (analysts building forecasting or
decision models, an AI title, an ML data platform). Only 7 change what is shown end to end
(tune 1273, 1418, 2514, 2617, 3357; test 1599, 1407); the rest are closed by seniority.
Disclosure: for four of the tuning jobs (1273, 1418, 2617, 3357) v10's answer had already
been seen in the extras list above; they were changed because a written rule covers them.
No test-half model answer was looked at.

Kept hidden where the AI-title rule conflicts with a more specific v1.2 hide rule (for the
user to decide): 121 "Lead Product Designer, AI" (UX designers of AI), 453 "ML Data
Operations" associate (annotation), 53 "AI Studio" content operations, 1035/1036/1038
"Agentic Acquisition Specialist" (sales), 1399 "AI Enablement" analyst (AI tool training).

Re-scored, Luna default, per call (shown missed / extra end to end):

| | tune | test (sealed) | relevance missed tune / test |
|---|---|---|---|
| 1.3.0 | 5.7 / 10.3 | 2.7 / 4.0 | 15.3 / 13.3 |
| 1.4.0 | 1.3 / 16.0 | 1.0 / 12.3 | 4.0 / 3.7 |
| **v10** | **1.3 / 12.3** | **2.0 / 7.7** | **4.0 / 5.0** |

Relevant jobs now: tune 107 (40 shown end to end), test 88 (29). The ranking is unchanged:
v10 misses far fewer jobs than 1.3.0 for a few more extras. Its remaining tuning-half
misses are the new uncertain grey zone (76, 555, 1536, 2514); its visible extras are the
"using AI tools" and vague-mention patterns listed above.

## Addendum 2026-10-06: Luna reasoning effort (default / high / xhigh, 3 calls per job each)

`run_effort_2026-10-05.sh`, scored on the re-checked truth. Shown jobs missed / extra per
call, tuning + sealed halves added (966 jobs, 69 shown end to end):

| | default | high | xhigh |
|---|---|---|---|
| 1.3.0 | 8.4 / 14.3 | 8.7 / 16.0 | 8.7 / 16.0 |
| 1.4.0 | 2.3 / 28.3 | 2.3 / 25.0 | 3.3 / 26.0 |
| **v10** | 3.3 / 20.0 | 2.0 / 21.6 | **1.3 / 22.6** |

v10 per half: default 1.3 / 12.3 tune, 2.0 / 7.7 test; high 1.0 / 11.3, 1.0 / 10.3;
xhigh 0.3 / 10.3, 1.0 / 12.3. Cost per call (v10): $0.00029 / $0.00038 / $0.00053.
Seconds per call (v10, mean / p95): 3.7 / 5.8, 5.6 / 9.5, 6.1 / 12.1.

- Effort does nothing for 1.3.0 and nothing consistent for 1.4.0.
- With v10, higher effort steadily removes misses (3.3 -> 2.0 -> 1.3) for 1-3 more extras.
  High vs xhigh differ by under one job per 1,000 and are within noise of each other.
- Earlier finding 4 ("xhigh does not help") was measured on the pre-re-check labels with
  two xhigh calls per job; it does not hold for v10 on the re-checked labels.
- Production is single-threaded: a 3,677-job evaluation at ~3.7 s/call takes about 3.8 h
  at default and about 6.2 h at xhigh (5.7 h at high). Cost per such scan: about $1.07 /
  $1.40 / $1.95. The benchmark over-samples hard jobs, so per-scan error counts are not a
  simple multiple of the table.

## Decisions 2026-10-06

- **Effort for production: Luna high.** The user chose high over xhigh (about half an hour
  less per scan, within noise of xhigh on misses).
- **Title-rule conflicts stay hidden** (53, 121, 453, 1035-1038, 1399); recorded in policy
  v1.2 under the title rule.
- **No broad tuning.** Misses are at the noise floor of a 69-positive benchmark; one
  targeted fix only: prompt v11 = v10 + "testing with AI tools is not testing AI systems",
  measured against v10 at high effort by `run_v11_2026-10-05.sh`.

## Addendum 2026-10-06: v11 vs v10 at Luna high (3 calls per job) -- v11 rejected

Shown missed / extra per call: tune v10 1.0 / 11.3, v11 2.0 / 9.0; sealed test v10 1.0 /
10.3, v11 1.3 / 12.3. Jobs flipping between calls: tune 12 -> 8, test 7 -> 13. Same cost.

The fix did what it targeted on the tuning half (2822, a QA role prompt-engineering its
tests, left the extras), but the stronger "using AI tools" wording spilled over: on 3357, an
analyst who designs decision models and also uses AI tools for reporting, v11 answered
not_ai on 2 of 3 calls ("AI tools are mentioned only as a way to automate reporting"), a
new miss. On the sealed half v11 is slightly worse on both misses and extras. All
differences are about one job, i.e. within noise, and the agreed rule was "if it adds a
miss, stay on v10". **Production prompt: v10, Luna high effort.**
