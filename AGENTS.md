# Job Finder repository instructions

## Read before changing anything

- Read `docs/01_job_posting_discovery_system_design.md` for the product and architecture.
- Read `docs/02_job_posting_discovery_implementation_guide.md` for the incremental build approach.
- Read `docs/03_job_posting_discovery_phased_execution_plan.md` in full. It is the authoritative execution order, test plan, phase-gate definition, and human-checkpoint protocol.
- Read `docs/04_product_decisions.md` for approved search behavior when that file exists.
- Inspect Git status before editing. Preserve pre-existing user files and unrelated untracked content.

## Execution behavior

- Implement the execution plan phase by phase. Do not skip prerequisites, tests, manual evidence, completion gates, or full-company validations.
- Continue autonomously through routine implementation, debugging, testing, and documentation.
- Stop only at an applicable heading beginning `STOP — Human checkpoint`, an applicable `CONDITIONAL STOP — Human checkpoint`, or when continuation needs authority the user has not granted.
- At a checkpoint, follow the stop-and-resume protocol in the execution plan. Never infer approval from silence.
- Maintain `docs/implementation_progress.md` once implementation begins. Record the active phase, passed gates, relevant commits, pending checkpoint, unresolved defects, and review-artifact paths. Update it at phase boundaries and before stopping.

## Approved first-release scope

- The tool is manually triggered. Scheduling and notifications are deferred.
- Process the full canonical company seed, not only a priority tier.
- Use a rolling ten-day listing window.
- Apply deterministic role and India-location filters before description retrieval and LLM evaluation.
- Use the LLM to determine whether a role is open to candidates with fewer than five years of experience.
- Keep uncertain publication dates visible and measured. Do not choose a permanent include or exclude policy until the execution plan's date-coverage checkpoint is reviewed by the user.

## Source-data rules

- `data/company_seed.csv` is the canonical first-release company list.
- The Excel workbook recorded in `data/README.md` is provenance material. Treat it as immutable: do not move, rename, overwrite, reformat, or delete it.
- Treat `careers_url_hint` as discovery evidence, not an approved official source. Phase 2 must verify each source before enabling it.
- Preserve all 330 seed companies in accounting reports. Any unsupported, blocked, or disabled company needs an explicit reason and the required user decision.
- Do not hand-edit generated company IDs. If source data changes, use a documented deterministic regeneration process and review the diff.

## Safety and external access

- Use public job sources only. Do not bypass authentication, CAPTCHA, rate limits, robots controls, or other access restrictions.
- Never ask the user to paste API keys, cookies, session tokens, or passwords into chat.
- Store secrets only in ignored local environment files. Keep placeholders in `.env.example`.
- Do not print, log, stage, or commit secrets, cookies, full browser sessions, local databases, cached responses, generated reports, or temporary diagnostics.
- Use bounded requests, truthful client identification, timeouts, retries, backoff, and conservative request volume.
- Use disposable test state for destructive tests. Follow checkpoint H7 before modifying real job-history state.

## Engineering and Git

- The implementation guide assumes Python. Choose and document a supported Python version in Phase 0 before adding production dependencies.
- Prefer standard-library or established dependencies with a clear need. Keep source-specific behavior inside adapters or configuration.
- Add regression evidence before fixing a confirmed parser or filtering defect.
- Run focused tests after each change and the repository validation command before each commit once it exists.
- Commit every meaningful completed change separately with a focused message. Do not accumulate an entire phase into one commit.
- Before committing, inspect the staged diff and exclude secrets, generated state, temporary files, the provenance workbook, and unrelated user content.
- Do not commit knowingly broken work merely to reach a checkpoint.
