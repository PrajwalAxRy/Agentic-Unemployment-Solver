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
