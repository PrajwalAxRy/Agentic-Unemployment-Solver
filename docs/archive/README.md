# Archive — historical, excluded from AI context

These files record how the system was originally built. **They describe behaviour that no
longer exists**: an allowlist title filter passing ~11% of titles, and a seniority-only LLM
call. Both were replaced by the `to_change.md` rewrite.

They are excluded from assistant reads via `.claude/settings.json`, because an assistant
that reads them builds the wrong model of the pipeline — that is exactly what happened
before they were moved here.

**They are kept, tracked in Git, and must not be deleted.** They hold evidence recorded
nowhere else:

| File | What only it records |
|---|---|
| `03_..._phased_execution_plan.md` | The H0–H11 checkpoint definitions, cited by name across the repo |
| `implementation_progress_to_2026-09-29.md` | Commit-to-phase mapping, and why each source was enabled or failed closed |
| `01_..._system_design.md` | Original design rationale table and adapter-family strategy |
| `source_discovery_workflow.md` | The source-research prompt and aggregator guardrails |
| `02_..._implementation_guide.md` | Build narrative (largely duplicated by 03) |

## Reading these deliberately

A human can open them normally. If you need an assistant to consult one — say, to recover
what H6 covered — paste the relevant excerpt into the conversation rather than lifting the
deny rule. That keeps the exclusion intact while still getting the answer.

Current behaviour: `CLAUDE.md`. Decisions and their reasoning: `docs/decisions.md`.
