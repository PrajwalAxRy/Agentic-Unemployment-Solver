# Job Posting Discovery Phased Execution Plan

Version 1.1

Date: 20 September 2026

## Objective

Deliver a manually triggered job discovery tool that:

- Reads a fixed, validated company registry.
- Fetches public job listings through reusable source adapters.
- Considers roles from a rolling ten-day window.
- Filters by role and location.
- Suppresses postings already processed.
- Uses an LLM to assess seniority from the job description.
- Reports new matching jobs, uncertain cases, and source failures.

The plan intentionally postpones scheduling, notifications, automatic applications, full job-lifecycle tracking, and fully automatic source repair. Those features should reuse the first-release foundation rather than complicate it prematurely.

## How to execute this plan

Each phase must finish with evidence, not merely completed code. The required evidence includes:

1. Automated tests appropriate to the layer.
2. Live verification against representative companies.
3. Adapter-group or full-company validation where specified.
4. Manual review of the output.
5. Updated documentation and configuration.
6. Focused Git commits for every meaningful completed change.

Do not start the next phase while the current phase has an unexplained failure that could invalidate later assumptions.

## Agent execution and stop-signal protocol

This plan is intended to be executable by an LLM coding agent. The agent should continue autonomously through implementation, testing, debugging, documentation, and focused Git commits unless it reaches an explicit stop signal or needs authority that the user has not granted.

### Suggested build prompt

The user can start or resume implementation with this prompt:

> Read `docs/03_job_posting_discovery_phased_execution_plan.md` in full and implement it phase by phase. Inspect the existing repository before changing anything. Work autonomously through coding, tests, documentation, and focused Git commits. Follow every completion gate and technical stop condition. Stop and ask me for input only at an applicable `STOP — Human checkpoint` or when continuation requires authority not already granted. When stopping, give me the exact action, path, URL, decision, or non-secret configuration I need to provide, plus the exact reply that will resume work. Preserve completed work and resume from the last checkpoint after I respond.

The agent should keep a small, version-controlled implementation progress record containing the current phase, completed gates, latest relevant commit, pending checkpoint, and links to review artifacts. Update it at phase boundaries and before every human checkpoint so a later session can resume without repeating discovery or completed work.

### Exact stop marker

An agent must treat a heading beginning with the following text as a hard boundary:

```text
STOP — Human checkpoint
```

At a hard boundary, the agent must:

1. Finish all safe work listed before the checkpoint.
2. Run the available automated tests and preserve the results.
3. Commit any coherent completed change before stopping. Do not commit knowingly broken work merely to reach the checkpoint.
4. State what is complete, what remains, and the exact reason human input is required.
5. Give the user one short, concrete action or decision request.
6. Point to the exact file, report, URL, or screen the user should inspect.
7. State the acceptable reply that will allow work to resume.
8. Stop the turn. Do not infer approval from silence or continue into work that depends on the answer.

After the user responds, the agent must record the decision in the repository when applicable, validate it, commit that meaningful change, and resume from the named checkpoint. The agent should not repeat already completed work.

### Conditional stop marker

A heading beginning with this text is a stop only when its listed trigger is true:

```text
CONDITIONAL STOP — Human checkpoint
```

If the trigger is false, the agent should record why the checkpoint did not apply and continue without interrupting the user. A lack of confidence by itself is not enough: the agent must first exhaust safe inspection, tests, documentation, and available read-only tools.

### What requires a human checkpoint

Stop when continuation requires one of the following:

- A product preference that is not already encoded in an approved profile or this plan.
- A credential, account login, CAPTCHA, multi-factor authentication, or action in a user-controlled browser.
- Acceptance of website terms, access restrictions, or another policy decision.
- Visual inspection that available tools cannot perform reliably.
- Approval to exclude an important company from first-release coverage.
- Approval of subjective role, location, date, or seniority behavior based on real examples.
- A destructive or difficult-to-reverse operation on real local state.
- Approval to apply an LLM-proposed repair to active configuration.
- A test that genuinely requires another person or the passage of real time.
- Final release approval or creation of a release tag.

Do not stop merely to ask the user to run commands, edit ordinary source files, install normal project dependencies, fix lint failures, inspect machine-readable output, or perform work the agent can safely complete and verify itself.

### Standard user requests at a checkpoint

For local secrets, use this pattern:

> I have created or updated the non-secret `.env.example`. Please add the listed variables to your local `.env`; do not paste secret values into chat. Reply `configured` when finished. I will verify only that the variables are present and will not print their values.

For manual inspection, use this pattern:

> Please open `<exact artifact or URL>` and inspect `<specific items>`. Record corrections in `<exact file or reply format>`, then reply `review complete`. I will apply or validate the corrections before continuing.

For a decision, use this pattern:

> I need your decision on `<question>`. My recommendation is `<option and reason>`. Reply with `<allowed answers>`; I will record the decision before continuing.

The request must use the actual paths, variable names, commands, proposal IDs, and choices created during implementation. Never ask the user to paste a secret, session cookie, or private browser token into chat.

### Checkpoint index

| ID | Phase | Trigger | Required human response |
|---|---|---|---|
| H0 | 0 | Company workbook or machine-specific setup remains ambiguous after inspection | Confirm the exact input or perform the named local action |
| H1 | 1 | Draft search policy and examples are ready | Approve or correct roles, locations, date policy, and seniority target |
| H2 | 2 | Source proposals and exceptions are ready | Approve reviewed sources, access decisions, and initial coverage scope |
| H3 | 3 | A representative portal cannot be verified reliably with available tools | Perform the named browser checks |
| H4 | 4 | First-release coverage would exclude or bypass an important source | Approve the exclusion, fallback, or additional adapter work |
| H5 | 5 | Source date meaning remains ambiguous and affects ten-day inclusion | Choose or approve the documented date treatment |
| H6 | 6 | Real role and location samples are ready | Approve or correct filtering behavior |
| H7 | 7 | Real state must be reset, replaced, or irreversibly migrated | Approve the exact operation after backup evidence |
| H8 | 8 | Mocked LLM integration passes and live validation needs credentials | Configure local provider variables without sharing secrets |
| H9 | 8 | Evaluation results and quality recommendation are ready | Approve the quality threshold and unresolved uncertainty policy |
| H10 | 9 | End-to-end command and runbook are ready | Perform the human usability review |
| H11 | 10 | A live repair proposal is ready for activation | Approve or reject the specific proposal |
| H12 | 11 | A pilot run completes and the next run requires a later real day | Return later and authorize the next pilot run |
| H13 | 11 | Release evidence is complete | Approve release and optional tag creation |

Technical stop conditions at the end of each phase are not automatically user tasks. The agent must diagnose and try to resolve them. Escalate to the user only if the remaining blocker matches a hard or conditional human checkpoint above.

## Delivery principles

- Build one observable behavior at a time.
- Keep source-specific behavior inside adapters or configuration.
- Preserve original source fields alongside normalized fields.
- Use fixtures for fast, repeatable tests.
- Use controlled live checks to confirm fixtures still represent the real source.
- Test every company affected by an adapter change.
- Run full-registry checks after cross-cutting behavior changes.
- Avoid LLM calls until cheap deterministic filters have passed.
- Treat failed or suspicious sources as visible failures, not empty boards.
- Add a regression fixture before fixing a parser bug.
- Commit working, reviewable units instead of accumulating a large phase-ending commit.

## Phase map

| Phase | Name | Primary exit result |
|---|---|---|
| 0 | Repository foundation | Reproducible project structure and validation command |
| 1 | Product and data contracts | Versioned schemas, policies, and test examples |
| 2 | Company source inventory | Every company mapped, blocked, or explicitly unsupported |
| 3 | Adapter foundation | Shared request layer and one complete ATS adapter |
| 4 | Adapter coverage | Reusable adapters cover the approved company scope |
| 5 | Normalization and recency | Consistent job records and ten-day decisions |
| 6 | Role and location filters | Explainable, manageable candidate set |
| 7 | Duplicate persistence | Repeated scans are idempotent |
| 8 | LLM seniority evaluation | Structured, tested, cached seniority decisions |
| 9 | Manual trigger and report | One command produces an understandable result |
| 10 | Resilience and repair evidence | Source failures are contained and diagnosable |
| 11 | Full-registry pilot | Repeated real scans satisfy release criteria |

## Global test layers

| Test layer | Purpose | Required timing |
|---|---|---|
| Unit tests | Validate pure schemas, normalization, identity, and filters | During every implementation change |
| Fixture adapter tests | Protect parsing and error behavior | For every adapter change |
| Representative live checks | Confirm fixtures still match real portals | Before an adapter commit |
| Adapter-group scan | Verify all companies using one adapter | After adapter or shared request changes |
| Full-registry lightweight scan | Verify configuration, listing access, and cross-cutting behavior | At designated phase gates |
| Full-pipeline scan | Validate filters, state, LLM evaluation, and reporting | Starting in Phase 9 |
| Manual review | Detect wrong links, missing postings, and misleading decisions | At every phase gate |

## Global Git workflow

### Commit after every meaningful change

A meaningful change is one coherent unit such as:

- A new schema or migration.
- One adapter.
- One shared normalization behavior.
- One filtering capability.
- One bug fix with regression coverage.
- One reviewed company-configuration batch.
- One report behavior.
- One substantial documentation update.

### Before each commit

- [ ] Confirm the change has one purpose.
- [ ] Run focused automated tests.
- [ ] Run fixture tests where source behavior is involved.
- [ ] Run the required adapter-group or full-registry gate.
- [ ] Review live samples where required.
- [ ] Inspect the staged diff.
- [ ] Remove generated reports, local state, secrets, and unrelated files from staging.
- [ ] Update documentation when behavior changes.
- [ ] Use a message that describes the delivered behavior.

### Commit message pattern

Use short imperative summaries, for example:

```text
feat: add greenhouse listing adapter
feat: apply rolling ten-day recency policy
feat: suppress repeated job identities
fix: reject workday login page as job data
data: verify ashby company source mappings
test: cover pagination cursor loops
docs: explain date uncertainty policy
```

## Phase 0 Repository foundation

### Objective

Create a reproducible development environment where source code, configuration, fixtures, local state, reports, and secrets remain separate.

### Prerequisites

- Existing Git repository.
- Existing company workbook remains untouched unless a later phase explicitly migrates its data.
- Agreed implementation language and supported version.

### Deliverables

- Project directory structure.
- Dependency declaration.
- Formatting, linting, type-checking, and test configuration.
- One validation command.
- Ignore rules.
- Sample configuration without secrets.
- Basic contributor and run instructions.

### Implementation tasks

1. Create application packages for:
   - Core schemas and models.
   - Source adapters.
   - Normalization.
   - Filters.
   - Persistence.
   - LLM matching.
   - Reporting.
   - Command-line orchestration.
2. Create directories for:
   - Configuration.
   - Test fixtures.
   - Documentation.
   - Generated reports.
   - Local state.
3. Choose dependency management and lock dependency versions.
4. Configure formatting, linting, typing, and tests.
5. Add a single local validation command.
6. Add ignore rules for:
   - Secrets.
   - Local databases.
   - Generated reports.
   - Browser captures.
   - Cached HTTP responses.
   - Temporary LLM outputs.
   - Build and test caches.
7. Add a minimal application import or version command.
8. Add a smoke test.

### Automated tests

- Project package imports successfully.
- Validation command runs from a fresh shell.
- Test discovery works.
- A sample configuration loads.

### Manual work

- Review current Git status before adding files.
- Identify pre-existing untracked user content and keep it outside commits.
- Confirm the existing company workbook remains intact.
- Generate a temporary report and database and confirm ignore rules work.
- Confirm no secret value exists in the sample environment file.

### CONDITIONAL STOP — Human checkpoint H0: resolve local input or setup ambiguity

Trigger this checkpoint only if the agent has inspected the repository and workbook but still cannot determine the authoritative workbook, worksheet, company-name column, or a machine-specific action that only the user can perform.

Before stopping, the agent must document what it found and narrow the ambiguity to the smallest possible question. It must not ask the user to perform routine scaffolding, dependency installation, file creation, or Git work.

Ask the user to identify the exact file, sheet, or column, or to perform the one named local action. Resume only after the agent can load the chosen input or verify that the required action succeeded. Record stable workbook mapping decisions in configuration or documentation; never modify the source workbook merely to simplify parsing.

### Completion gate

Phase 0 is complete when a clean checkout can install the project and run the documented validation command without manual repair. Generated local state must remain outside Git.

### Commit sequence

1. `chore: scaffold job discovery project`
2. `test: add project validation commands`
3. `docs: add local development instructions`

Combine only when the changes are too small to be useful separately.

### Stop conditions

Stop before Phase 1 if:

- Validation cannot run repeatably.
- Generated state appears in Git status.
- The project requires undocumented machine-specific setup.

## Phase 1 Product and data contracts

### Objective

Translate the agreed behavior into versioned configuration and data contracts before integrating live company portals.

### Prerequisites

- Phase 0 validation command passes.
- Initial target-role and location intentions are available.

### Deliverables

- Search-profile schema.
- Company-source schema.
- Normalized-job schema.
- Adapter-result and diagnostic schema.
- Ten-day recency specification.
- Date-uncertainty policy.
- Role and location examples.
- Seniority evaluation examples.

### Implementation tasks

1. Define the search-profile schema:
   - Profile ID and version.
   - Target role families.
   - Title synonyms.
   - Title exclusions.
   - Accepted locations and aliases.
   - Remote and hybrid policy.
   - Seniority target.
   - Ten-day window.
   - Date-uncertainty mode.
2. Define the company-source schema:
   - Stable company ID.
   - Display name.
   - Official careers URL.
   - Adapter type.
   - Adapter parameters.
   - Identity strategy.
   - Date strategy.
   - Detail strategy.
   - Enabled state.
   - Confidence and evidence.
3. Define the normalized-job schema.
4. Define adapter result states and diagnostics.
5. Define the rolling ten-day calculation using an explicit scan time.
6. Define which date bases are reliable, uncertain, or excluded.
7. Add schema versioning and compatibility behavior.
8. Add configuration hashing for reproducibility.

### Automated tests

- Valid search profiles load.
- Missing role or location configuration fails clearly.
- Valid company sources load.
- Required adapter parameters depend on adapter type.
- Invalid URLs fail validation.
- Unknown schema versions follow the compatibility policy.
- Ten-day boundary tests cover:
  - Exactly ten days.
  - One second inside.
  - One second outside.
  - Different timezones.
  - Date-only values.
  - Missing values.
- Configuration hashes remain stable for equivalent content.

### Manual work

- Write concrete target-role examples.
- Write concrete title exclusions.
- Review city aliases, regional rules, and remote policy.
- Decide strict or permissive handling of uncertain dates.
- Write at least ten seniority examples with expected outcomes.
- Confirm a person can classify each example from the written policy.

### STOP — Human checkpoint H1: approve the search policy

The agent must first create a review artifact containing:

- Proposed role families, synonyms, and exclusions with examples.
- Accepted locations and aliases.
- Remote, hybrid, multi-location, and missing-location treatment.
- Strict or permissive treatment of uncertain dates.
- The seniority target and at least ten labelled examples.
- Any assumptions and a recommended choice for each unresolved item.

The agent must provide the exact path to that artifact and ask the user to approve it or return corrections. A suitable request is: “Please review `<path>` and reply `approved`, or list corrections by section.”

Do not begin company-source discovery until the user has approved these product choices. After approval, encode the decisions in the versioned search profile and policy documentation, run schema tests, and commit the approved baseline before continuing.

### Full-company validation

Run every row from the current company list through the minimum source-schema loader. Missing source details may remain explicit gaps at this stage, but every company must be counted. The validation report should show:

- Total companies.
- Duplicate names or IDs.
- Missing official URLs.
- Missing adapter types.
- Invalid configuration.

### Completion gate

Phase 1 is complete when adapters can target stable contracts and product decisions are represented by versioned configuration rather than hard-coded assumptions.

### Commit sequence

1. `feat: add search profile schema`
2. `feat: add company source and job schemas`
3. `docs: define recency and date uncertainty policy`
4. `test: add product contract examples`

### Stop conditions

Stop before Phase 2 if:

- Role and location rules still depend on portal behavior.
- Date uncertainty has no agreed treatment.
- The normalized job record contains fields that only one ATS can produce.

## Phase 2 Company source inventory

### Objective

Map every fixed-list company to a verified official source, reusable adapter family, and required parameters, or give it an explicit unsupported status.

### Prerequisites

- Company-source schema exists.
- Registry validator exists.
- Full company list is available.

### Deliverables

- Reviewed company-source registry.
- LLM-assisted discovery prompt and output schema.
- Evidence and confidence records.
- Adapter-family coverage report.
- Prioritized adapter backlog.
- Explicit unsupported and blocked-source list.

### LLM-assisted discovery task

For each company, request:

- Official careers URL.
- Relevant regional or country board.
- ATS or source family.
- List endpoint or search interface.
- Board token, tenant, site slug, locale, or required parameters.
- Pagination behavior.
- Job ID field.
- Publication-date field and confidence.
- Title and location fields.
- Detail-fetch behavior.
- Evidence.
- Confidence.
- Any access or terms concern.

The discovery output is a proposal, not approved configuration.

### Implementation tasks

1. Create the registry storage format.
2. Build the registry validator.
3. Build a discovery-result importer that still requires review.
4. Add summary reporting by adapter and confidence.
5. Add explicit statuses such as:
   - Proposed.
   - Reviewed.
   - Enabled.
   - Disabled.
   - Blocked.
   - Unsupported.
   - Custom adapter required.
6. Process the company list in reviewable batches.
7. Preserve evidence and discovery date.

### Automated tests

- Duplicate company IDs fail.
- Unknown adapter names fail.
- Adapter-specific missing parameters fail.
- Enabled low-confidence records fail unless explicitly approved.
- Every input company must appear in the output accounting report.
- Blocked and unsupported companies require a reason.

### Manual work

- Open every low-confidence proposal.
- Verify the page belongs to the intended company.
- Check for regional or India-specific job boards.
- Exclude recruiter and aggregator copies.
- Review source terms and access restrictions.
- Select representative companies for each adapter family.
- Include different board sizes in the representative sample.
- Approve adapter implementation priority based on coverage and source simplicity.

### STOP — Human checkpoint H2: approve sources and first-release scope

Before stopping, the agent must finish automated source discovery, verify high-confidence proposals with read-only checks, and generate a concise review artifact. The artifact must separate:

- Verified official sources recommended for enablement.
- Low-confidence or conflicting source proposals requiring inspection.
- Login, CAPTCHA, terms, or access-policy concerns.
- Companies requiring custom adapters.
- Companies proposed as blocked or unsupported.
- Recommended adapter priority and projected coverage.

Ask the user to inspect only the unresolved proposals and policy decisions, with direct URLs and a clear recommended disposition. The user may approve the recommendations or provide corrections. Do not enable low-confidence sources, accept access-policy risk, or remove an important company from the first-release scope without the user's explicit decision.

After the response, update source statuses and evidence, run the complete inventory audit, and commit each reviewed registry batch separately. Resume only when every company is accounted for and all unresolved scope decisions are recorded.

### Full-company validation

The inventory audit must prove:

- Every company appears exactly once.
- Every enabled company has a verified official URL.
- Every enabled company has an adapter or custom-adapter status.
- Every unsupported or blocked source has a reason and fallback.
- Every low-confidence source has been reviewed.
- The adapter coverage counts reconcile to the full list.

### Completion gate

Phase 2 is complete when the inventory accounts for every company and provides enough evidence to choose and configure adapters without repeating source discovery during normal scans.

### Commit sequence

1. `feat: add company registry validator`
2. `feat: add source discovery result format`
3. `data: add reviewed company sources batch one`
4. Continue one commit per reviewable batch.
5. `data: complete company source inventory`
6. `docs: record adapter coverage and exceptions`

### Stop conditions

Stop before Phase 3 if:

- Company counts do not reconcile.
- Unreviewed low-confidence sources are enabled.
- The first adapter choice is based on assumptions rather than the inventory.

## Phase 3 Adapter foundation

### Objective

Build shared request and adapter behavior, then prove it with one high-coverage structured ATS.

### Prerequisites

- Adapter interfaces and schemas are stable.
- The source inventory identifies the first adapter family.
- Representative companies are selected.

### Deliverables

- Shared HTTP client.
- Adapter base interface.
- First adapter fixtures.
- First working ATS adapter.
- Source verification command.
- Adapter health diagnostics.

### Shared client work

Implement:

- Truthful client identity.
- Bounded connection and response timeouts.
- Bounded retries.
- Backoff and rate-limit handling.
- Content-type validation.
- Redirect metadata.
- Response-size safeguards.
- Sanitized diagnostic capture.
- Test hooks for saved fixtures.

### First adapter work

1. Capture healthy, empty, malformed, and blocked fixtures.
2. Write parser tests before live integration.
3. Implement listing retrieval.
4. Implement pagination.
5. Map external ID.
6. Map title and location.
7. Map publication evidence and date basis.
8. Map canonical job URL.
9. Determine whether detail fetch is required.
10. Implement source-specific validation.
11. Implement the source verification command.

### Automated tests

- Healthy fixture produces expected jobs.
- Multi-page fixture produces all jobs exactly once.
- Valid empty fixture produces a healthy empty result.
- Malformed fixture fails with a parser diagnostic.
- Login or access-block fixture is rejected.
- Redirect behavior is visible.
- Stable IDs and canonical URLs remain stable.
- Detail retrieval maps the expected description when required.

### Representative live checks

For each selected company:

- Compare fetched count with the visible portal.
- Open several returned jobs.
- Verify title and location.
- Verify canonical URL.
- Verify publication-date meaning.
- Verify pagination on a larger board.
- Verify empty-board behavior if a known empty board exists.

### Adapter-group validation

Run the lightweight listing verifier for every company mapped to this adapter.

Required output:

- Company.
- Configuration version.
- Request outcome.
- Job count.
- Page count.
- Missing-field count.
- Date-basis distribution.
- Exception category.

Review every unexpected zero, failure, and count anomaly.

### Manual work

- Determine whether exceptions are configuration mistakes or shared adapter defects.
- Correct registry parameters separately from parser logic when possible.
- Preserve fixtures for every confirmed parser defect.
- Review request volume and access policy.

### CONDITIONAL STOP — Human checkpoint H3: inspect an unverifiable portal

Trigger this checkpoint only when available network or browser tools cannot reliably establish pagination completeness, visible job counts, direct-link behavior, publication-date meaning, or whether an apparent empty result is genuine. Typical triggers include client-side-only rendering, login, CAPTCHA, regional redirects, or content visible only in the user's authenticated browser.

Before stopping, save the automated evidence, identify the exact unresolved fact, and provide the smallest useful checklist with direct URLs. Ask the user to report only observable facts such as the visible result count, whether another page exists, a sample title and location, the displayed date label, and whether the direct job link opens.

Do not ask the user to inspect ordinary JSON or HTML that the agent can retrieve itself. Resume after the observation is recorded as evidence and the affected configuration or adapter test is updated. Never request session cookies or browser tokens.

### Completion gate

Phase 3 is complete when every valid company in the first adapter family works through the shared interface or has a reviewed, explicit exception.

### Commit sequence

1. `feat: add shared source request client`
2. `feat: define adapter runtime interface`
3. `test: add first ATS response fixtures`
4. `feat: add first ATS listing adapter`
5. `feat: add source verification command`
6. `data: correct first ATS company mappings`

### Stop conditions

Stop before Phase 4 if:

- The adapter requires multiple untested company-specific parser branches.
- Empty and failed sources cannot be distinguished.
- Pagination completeness is unknown.

## Phase 4 Adapter coverage

### Objective

Implement reusable adapters until the approved first-release company coverage is met.

### Prerequisites

- First adapter establishes the implementation pattern.
- Prioritized adapter backlog exists.

### Deliverables

- Additional adapter families.
- Fixtures and tests for each adapter.
- Reviewed company parameters.
- Updated coverage report.
- Explicit custom and unsupported-source backlog.

### Work package for each adapter

1. Confirm required configuration parameters.
2. Capture representative fixtures:
   - Healthy list.
   - Empty list.
   - Multiple pages.
   - Malformed response.
   - Access restriction where available.
3. Implement list retrieval.
4. Implement pagination.
5. Map identity, title, location, date evidence, and URL.
6. Implement detail retrieval only when necessary.
7. Add adapter-specific validation.
8. Add diagnostics.
9. Run focused tests.
10. Run representative live checks.
11. Run every company mapped to the adapter.
12. Review and correct exceptions.
13. Commit the adapter and configuration corrections.

### Automated tests for every adapter

- Healthy list parsing.
- Empty list behavior.
- Pagination completeness.
- Stable identity.
- Canonical URL.
- Date mapping.
- Required-field failure.
- Access-block detection.
- Detail retrieval when required.

### Manual work

- Confirm official source and parameters.
- Compare live counts and sample fields.
- Determine whether search-only behavior is complete enough.
- Choose native employer alerts instead of bypassing controls.
- Review large boards for complete pagination.
- Review small boards for false empty results.

### CONDITIONAL STOP — Human checkpoint H4: approve a coverage exception

Trigger this checkpoint when an important company cannot be supported safely with the planned adapters, when access controls make automated collection inappropriate, or when continuing requires materially more custom work than the approved first-release scope.

The agent must first present the company, observed limitation, attempts made, evidence, estimated implementation cost, and a recommendation among: add custom adapter work now, mark unsupported for this release, use a native employer alert, or remove the company from the approved scope. Ask the user to choose one of those explicit dispositions.

Do not bypass access controls. Do not silently reduce coverage. After the user decides, record the exception, reason, fallback, and revisit condition in the registry and coverage report before continuing.

### Adapter-group completion gate

Before committing an adapter, every mapped company must be successful, valid empty, intentionally unsupported, blocked, or documented with a reviewed exception.

### Full-registry validation

After the planned adapter set is complete, run listing verification over all enabled companies.

Reconcile:

- Registry total.
- Enabled total.
- Successful total.
- Valid empty total.
- Unsupported total.
- Blocked total.
- Failed total.

The categories must account for every enabled company.

### Completion gate

Phase 4 is complete when supported adapters cover the approved first-release scope and every excluded source has a documented reason and fallback.

### Commit sequence

For each adapter:

1. `test: add <adapter> response fixtures`
2. `feat: add <adapter> listing adapter`
3. `data: verify <adapter> company mappings`

Shared fixes should be separate:

```text
fix: handle repeated pagination cursors
```

### Stop conditions

Stop before Phase 5 if:

- Coverage totals do not reconcile.
- High-priority unsupported sources have no decision.
- A shared request defect remains unresolved.

## Phase 5 Normalization and recency

### Objective

Make jobs from every adapter comparable and enforce the rolling ten-day rule with visible date evidence.

### Prerequisites

- Adapter list outputs satisfy the common job contract.
- Source date fields have documented meanings or uncertainty.

### Deliverables

- Shared text normalization.
- Location normalization.
- URL canonicalization.
- Timestamp normalization.
- Date-basis classification.
- Ten-day recency filter.
- Registry-wide recency metrics.

### Implementation tasks

1. Normalize safe whitespace and punctuation.
2. Preserve original title and location.
3. Produce normalized title and location tokens.
4. Normalize common city and region aliases.
5. Support multi-location postings.
6. Remove tracking parameters from canonical URLs.
7. Preserve parameters required for job identity.
8. Parse timestamps with timezone awareness.
9. Preserve date-only values without inventing precision.
10. Set date basis to `published`, `updated`, `first_seen`, or `unknown`.
11. Compare reliable timestamps with the rolling ten-day boundary.
12. Route uncertain dates according to the search profile.
13. Record accepted, rejected, and uncertain metrics.

### Automated tests

- Exactly ten days old.
- One second inside the window.
- One second outside the window.
- Different timezone offsets.
- Date-only source values.
- Future dates.
- Malformed dates.
- Updated dates kept uncertain.
- URL tracking parameters removed.
- Required job-ID query parameters preserved.
- Multi-location normalization.
- Location aliases.

### Full-registry lightweight validation

Run every enabled company through listing and normalization without detail fetches or LLM calls.

Collect by adapter:

- Listing count.
- Valid identity count.
- Valid URL count.
- Reliable publication-date count.
- Uncertain-date count.
- Invalid-date count.
- Inside-window count.
- Outside-window count.

### Manual work

- Open accepted, rejected, and uncertain examples from each adapter.
- Compare source-visible dates with normalized values.
- Investigate future, ancient, or implausibly uniform dates.
- Review adapters with unusually high uncertainty.
- Promote a date field to reliable only with evidence.
- Record adapter-specific date interpretation in configuration.

### CONDITIONAL STOP — Human checkpoint H5: decide ambiguous date treatment

Trigger this checkpoint only when the source-visible label or field meaning remains ambiguous after documentation review, live comparison, and fixture analysis, and that ambiguity changes whether jobs fall inside the ten-day window.

The agent must provide representative job URLs, raw date evidence, possible interpretations, the number of affected jobs, and its recommended treatment. Ask the user to choose whether the source should use the field as `published`, keep it `uncertain`, fall back to `first_seen`, or be excluded from strict ten-day results.

Resume after the decision is recorded in the adapter date strategy and covered by fixtures and boundary tests. If the approved Phase 1 policy already determines the answer, apply it and continue without stopping.

### Completion gate

Phase 5 is complete when every normalized job has a stable identity candidate, canonical URL, and explicit date basis, and the ten-day filter behaves consistently across adapters and timezones.

### Commit sequence

1. `feat: normalize job titles and locations`
2. `feat: canonicalize job URLs`
3. `feat: normalize publication dates and date basis`
4. `feat: apply rolling ten-day recency policy`
5. `data: correct reviewed adapter date strategies`

### Stop conditions

Stop before Phase 6 if:

- Date uncertainty is silently discarded.
- Canonical URLs merge distinct jobs.
- One adapter has unexplained date behavior.

## Phase 6 Role and location filters

### Objective

Reduce recent listings to the intended role and location set before retrieving descriptions or calling the LLM.

### Prerequisites

- Search-profile examples are reviewed.
- Shared normalization is stable.
- Ten-day candidate set is available.

### Deliverables

- Role-family filter.
- Title synonym and exclusion logic.
- Location filter.
- Remote and hybrid logic.
- Machine-readable filter reasons.
- Profile hashing.
- Filter reduction report.

### Implementation tasks

1. Normalize titles for matching without losing source text.
2. Match role families.
3. Apply title synonyms.
4. Apply exclusions with documented precedence.
5. Normalize location tokens.
6. Apply city, region, and country rules.
7. Apply remote and hybrid policy.
8. Handle multi-location postings.
9. Retain ambiguous locations only under the approved policy.
10. Return a structured decision and reason.
11. Version and hash the search profile.
12. Report counts after each filter.

### Automated tests

- Every example from Phase 1.
- Conflicting accepted and excluded title terms.
- Common abbreviations.
- Multi-role titles.
- City aliases.
- Country-only locations.
- Remote within an allowed geography.
- Remote outside an allowed geography.
- Hybrid locations.
- Multiple accepted and rejected locations.
- Missing location.
- Stable profile hashes.

### Full-registry validation

Run all recent normalized listings through the filters.

Produce:

- Recent listings before filtering.
- Role passes.
- Role rejections by reason.
- Location passes.
- Location rejections by reason.
- Final retained set by role family and location.
- Companies with zero retained jobs.

### Manual work

- Review at least twenty retained jobs or all retained jobs if fewer.
- Review at least twenty rejected jobs across different reasons.
- Check every role family.
- Check every accepted location category.
- Inspect companies with zero retained roles.
- Add regression examples for concrete mistakes.
- Adjust shared vocabulary rather than source-specific exceptions.

### STOP — Human checkpoint H6: approve role and location filtering

Before stopping, the agent must generate a human-readable sample report containing at least twenty retained jobs, at least twenty rejected jobs across different reasons, or all available jobs when fewer exist. Include original title, original location, decision, reason, company, and direct URL. Stratify the sample across role families, locations, adapters, and zero-result companies rather than taking only the first rows.

Ask the user to mark each disputed row as `should include`, `should exclude`, or `uncertain`, and to note any missing target vocabulary. The agent should provide the exact report path and a simple way to return corrections; the user should not need to inspect code.

After review, convert every correction into a general policy change or regression example, rerun the complete filter report, and commit the approved search-profile version. Do not continue to persistence while systematic false positives or false negatives remain unresolved.

### Completion gate

Phase 6 is complete when the surviving set is manageable for description retrieval and manual review finds no unresolved systematic role or location omission.

### Commit sequence

1. `feat: add role-family title filtering`
2. `feat: add title exclusions`
3. `feat: add location and work-mode filtering`
4. `test: add live filter regression examples`
5. `docs: record approved search profile version`

### Stop conditions

Stop before Phase 7 if:

- Broad synonyms admit many unrelated roles.
- Exclusions remove legitimate target roles systematically.
- A location parser problem explains zero results for multiple companies.

## Phase 7 Duplicate persistence

### Objective

Make repeated manual scans idempotent and prevent repeated description fetches and LLM calls.

### Prerequisites

- Stable identity fields are available from normalized listings.
- Filtered candidates can be produced without persistence.

### Deliverables

- Local database schema and migrations.
- Job-key generation.
- Job-state repository.
- Transactional pending and completed evaluation behavior.
- Scan lock.
- State inspection, backup, restore, and reset commands.

### Minimal database record

- Job key.
- Company and source.
- External ID.
- Canonical URL.
- Fallback fingerprint.
- First seen.
- Last seen.
- Description hash.
- Profile version.
- Prompt version.
- Evaluation status.
- Seniority result.

### Implementation tasks

1. Add versioned database migrations.
2. Implement job-key priority:
   - External source ID.
   - Canonical URL.
   - Fallback fingerprint.
3. Store observation before expensive evaluation.
4. Distinguish pending from completed evaluation.
5. Resume pending work after interruption.
6. Invalidate cached evaluation after description or profile change.
7. Add a single-run lock.
8. Add state inspection.
9. Add explicit reset.
10. Add backup and restore.

### Automated tests

- Same fixture run twice produces no new candidates the second time.
- Tracking parameter changes do not change identity.
- Separate external IDs remain separate.
- Fallback identity remains stable under harmless whitespace changes.
- Description change invalidates evaluation but not job identity.
- Profile change invalidates the relevant decision.
- Interrupted transaction resumes pending work.
- Concurrent scan attempts do not corrupt state.
- Migration upgrades an older test database.
- Backup and restore preserve records.

### Full-registry validation

1. Start from an explicit fresh test state.
2. Run all enabled companies through listing, recency, role, and location filters.
3. Record unseen identities.
4. Run the same pipeline immediately again.
5. Investigate every unexplained second-run identity.

### Manual work

- Review fallback fingerprints for accidental merges.
- Review companies where URLs change between runs.
- Perform one backup and restore using only documented commands.
- Confirm state and backups remain outside Git.
- Confirm reset is explicit and cannot be triggered accidentally by a normal scan.

### CONDITIONAL STOP — Human checkpoint H7: approve a real-state destructive action

Use disposable test state for migrations, reset tests, and failure drills; those do not require user approval. Trigger this checkpoint only if progress requires resetting, replacing, or performing a non-reversible migration on the user's real job history.

Before stopping, create and verify a backup, print the resolved path and record counts without exposing job-description content unnecessarily, explain exactly what will change, and provide the restore command. Ask the user to approve the one specific operation. A vague instruction such as “continue” is not approval for a different destructive target.

After approval, re-resolve and validate the target path, perform only the approved operation, verify record counts and restore readiness, and report the outcome before proceeding. Never treat normal test-database cleanup as authority to alter real state.

### Completion gate

Phase 7 is complete when repeated unchanged scans produce zero new identities and state maintenance is documented and tested.

### Commit sequence

1. `feat: add job state database migrations`
2. `feat: add stable job identity mapping`
3. `feat: persist pending and completed evaluations`
4. `feat: prevent overlapping scans`
5. `feat: add state maintenance commands`

### Stop conditions

Stop before Phase 8 if:

- Immediate reruns produce unexplained new jobs.
- Fallback matching merges distinct requisitions.
- A failed evaluation can become permanently suppressed.

## Phase 8 LLM seniority evaluation

### Objective

Determine seniority from job descriptions using a structured, explainable, cacheable LLM decision.

### Prerequisites

- Deterministic candidate pipeline works.
- Duplicate store suppresses repeated work.
- Seniority target and examples are approved.

### Deliverables

- Seniority taxonomy.
- Response schema.
- Versioned prompt.
- LLM client abstraction.
- Response validation and retry policy.
- Reviewed evaluation set.
- Decision cache integration.
- Usage reporting.

### Response schema

Require:

- `seniority_match`: `true`, `false`, or `uncertain`.
- `detected_level`: normalized level or `unknown`.
- `required_experience`: normalized years or `unknown`.
- `evidence`: short evidence from the description.
- `reason`: concise comparison with the target profile.

### Implementation tasks

1. Define seniority taxonomy.
2. Define and validate the JSON schema.
3. Write the prompt using the target profile and description.
4. Require evidence.
5. Add one retry for malformed output.
6. Route repeated invalid output to manual review.
7. Treat genuine ambiguity as `uncertain`.
8. Cache by job key, description hash, profile version, prompt version, and model policy.
9. Add request and usage limits.
10. Record model and prompt version with each decision.
11. Ensure no unnecessary job or personal data is sent.

### Reviewed evaluation set

Include examples with:

- Explicit years of experience.
- Entry-level wording.
- Senior title with weaker requirements.
- Junior title with advanced ownership.
- Staff or principal scope.
- Management requirements.
- Conflicting experience indicators.
- No seniority evidence.
- Description text containing irrelevant years.

For each example, store:

- Description fixture.
- Expected match result.
- Expected level when determinable.
- Human rationale.
- Important evidence.

### Automated tests

- Valid schema response.
- Rejection response.
- Uncertain response.
- Malformed response and retry.
- Repeated malformed response and manual review.
- Cache hit on unchanged input.
- Cache invalidation after description change.
- Cache invalidation after profile or prompt change.
- No call for old listings.
- No call for role or location rejections.
- No call for already evaluated unchanged jobs.
- Usage limit behavior.

### STOP — Human checkpoint H8: configure the live LLM provider

Reach this checkpoint only after the evaluator, schema validation, retry behavior, cache behavior, usage limits, and tests work with mocked responses.

Before stopping, the agent must:

1. Create or update `.env.example` with placeholder values and explanatory comments.
2. Confirm `.env` and equivalent secret files are ignored by Git.
3. Document the exact provider, model configuration, variable names, expected cost or usage guardrail, and a non-secret connectivity-test command.
4. If provider or model choice is still open, recommend one supported option and explain the tradeoff briefly.
5. Check whether the required variables are already present without printing their values.

If configuration is missing, ask the user to copy the example to the local `.env` and set the named variables, including the provider-specific API key such as `OPENAI_API_KEY`. Tell the user not to paste secret values into chat and to reply `configured` when finished. If an account login, billing action, or organization approval is required, name that action explicitly.

After the user replies, verify only presence and a redacted connectivity result. Never print, log, stage, or commit the secret. If connectivity fails, report the sanitized error and stop again with one concrete corrective request. Continue to live validation only after the guarded connectivity test succeeds.

### Limited live validation

Run a small unseen candidate batch and review every decision. Classify disagreements and add them to the evaluation set before changing the prompt.

Do not add company-specific prompt exceptions. Improve the shared profile, prompt, or evidence rules.

### Full-company validation

Run the complete registry through deterministic filters and evaluate only surviving unseen candidates.

Review:

- Candidate count reaching the LLM.
- Cache-hit rate.
- Request count.
- Match count.
- Rejection count.
- Uncertain count.
- Invalid-response count.
- All uncertain decisions.
- A representative sample of matches and rejections.

### Manual work

- Resolve ambiguous expected labels in the evaluation set.
- Approve a first-release quality threshold.
- Review every live match in the initial validation.
- Review evidence quality.
- Confirm request usage is acceptable.

### STOP — Human checkpoint H9: approve seniority quality

Before stopping, the agent must run the reviewed evaluation set and limited unseen batch, then produce a report containing aggregate metrics, every disagreement, every uncertain or invalid result, representative matches and rejections, evidence quality, model and prompt versions, request count, and estimated or measured usage.

Recommend a first-release quality threshold and state whether it passed. Ask the user to approve the threshold and uncertainty policy, or to correct specific expected labels. The user should review descriptions and evidence, not prompt implementation details.

After the response, update the labelled evaluation set and policy, rerun the evaluation, and commit the approved evaluation baseline separately from any prompt change. Every prompt change must include a regression example. Do not proceed if the threshold is unapproved or a systematic defect remains.

### Completion gate

Phase 8 is complete when the reviewed evaluation set meets the approved threshold, every result contains evidence, uncertainty remains visible, and repeated scans reuse cached decisions.

### Commit sequence

1. `feat: define seniority taxonomy and response schema`
2. `test: add reviewed seniority evaluation set`
3. `feat: add versioned LLM seniority evaluator`
4. `feat: cache seniority decisions`
5. `feat: report LLM request usage`
6. Prompt changes receive separate commits with regression examples.

### Stop conditions

Stop before Phase 9 if:

- Decisions lack evidence.
- Unchanged inputs create repeated LLM calls.
- False decisions show a systematic profile or prompt defect.
- Malformed output can be treated as a match.

## Phase 9 Manual trigger and report

### Objective

Provide one user action that runs the pipeline and returns an understandable report without notifications or scheduling.

### Prerequisites

- Sources, filters, state, and seniority evaluation work independently.

### Deliverables

- Manual scan command.
- Run orchestration.
- Progress output.
- Human-readable report.
- Machine-readable report.
- Run metrics.
- User runbook.

### Implementation tasks

1. Create a command such as `job-finder scan`.
2. Validate registry and profile before network work.
3. Display registry, profile, and schema versions.
4. Acquire the scan lock.
5. Process companies independently.
6. Continue healthy sources after a source failure.
7. Record run start, end, duration, and coverage.
8. Generate machine-readable JSON.
9. Generate Markdown or HTML for a person.
10. Put new matching jobs first.
11. Show date-uncertain candidates separately.
12. Show seniority-review candidates separately.
13. Show source failures separately.
14. Return a successful result for zero matches when coverage is complete.
15. Return a distinct partial or failed status when coverage is incomplete.

### Report fields for a matching job

- Company.
- Job title.
- Location.
- Source publication date.
- Date basis.
- First-seen time.
- Seniority decision.
- Seniority evidence.
- Direct URL.

### Automated tests

- Healthy run with matches.
- Healthy run with zero matches.
- Partial source failure.
- Complete run failure.
- Date-uncertain candidate.
- Seniority-uncertain candidate.
- Second unchanged run with no new matches.
- Report totals reconcile with stored run data.
- URLs and evidence match stored records.
- Exit statuses follow the declared contract.

### Full-registry validation

Run once from a deliberate fresh state and once immediately afterward.

Reconcile:

- Total companies.
- Enabled companies.
- Attempted companies.
- Successful companies.
- Failed, blocked, unsupported, and disabled companies.
- Total listings.
- Recent listings.
- Role candidates.
- Location candidates.
- Unseen identities.
- LLM matches.
- Uncertain evaluations.
- Second-run duplicate suppression.

### Human usability test

Ask a person who did not implement the command to:

1. Follow the runbook.
2. Trigger a scan.
3. Decide whether coverage is complete.
4. Open matching jobs.
5. Explain why a job was included.
6. Identify companies needing attention.
7. Find state backup and reset instructions.

Record misunderstandings and fix the report or runbook.

### STOP — Human checkpoint H10: perform the usability review

The agent must first run the full command itself, resolve technical failures, and provide a known-good runbook plus a representative report. This checkpoint tests human usability, not whether the command merely executes.

Ask the user, or another person who did not implement the command, to follow the runbook and answer the seven questions above. Provide the exact command and paths, and ask them to reply `usable` or list where they became confused. If asking another person is impractical, the user may perform the review.

After feedback, fix the interface, report, or runbook; rerun automated and full-registry validation; and repeat this checkpoint only for material usability failures. Do not teach around a confusing interface in chat when the product or documentation can be corrected.

### Completion gate

Phase 9 is complete when a nondeveloper can run the tool and distinguish new matches, no matches, uncertain results, and incomplete coverage.

### Commit sequence

1. `feat: add manual job scan command`
2. `feat: add scan run metrics`
3. `feat: add job discovery report`
4. `docs: add scan runbook and troubleshooting`

### Stop conditions

Stop before Phase 10 if:

- Zero matches and failed coverage look the same.
- A failed company prevents healthy results.
- The second run repeats unchanged jobs.
- The runbook requires source-code knowledge.

## Phase 10 Resilience and repair evidence

### Objective

Prevent silent omissions and collect enough evidence for a person or LLM to propose a safe source repair.

### Prerequisites

- Normal manual scans work.
- Run metrics and source diagnostics exist.

### Deliverables

- Expanded anomaly detection.
- Failure categories.
- Diagnostic reports.
- Targeted source verification.
- Failure drills.
- Guarded LLM repair proposal workflow.

### Implementation tasks

1. Add required-field checks per adapter.
2. Add content-type and page-type checks.
3. Detect login and CAPTCHA pages.
4. Detect result-count collapse.
5. Detect repeated pages and cursors.
6. Detect stale or impossible dates.
7. Categorize failures:
   - Temporary availability.
   - Rate limit.
   - Configuration error.
   - Source moved.
   - Schema change.
   - Parser defect.
   - Access restriction.
   - Unsupported source.
8. Save sanitized diagnostic summaries.
9. Add verification for one company, one adapter, or the full registry.
10. Create an LLM repair input containing evidence, not unrestricted authority.
11. Require a proposed change, confidence, and test plan.
12. Keep proposed repairs inactive until tests and approval pass.

### Failure drills

- Login page returned with status 200.
- CAPTCHA page.
- Required JSON field removed.
- Response type changed.
- Pagination cursor repeated.
- Network timeout.
- Rate limit with retry guidance.
- Historically large board suddenly returns zero.
- One company fails while peers remain healthy.
- LLM service unavailable.
- State database temporarily locked.

### Automated tests

- Every drill produces the intended category.
- Bounded retries stop.
- Suspicious zero results are not healthy empty results.
- Diagnostics exclude configured secrets.
- Healthy companies still complete.
- Repair proposals cannot modify active configuration directly.

### Full-registry validation

Run the source verifier over every enabled company. Review every degraded, failed, blocked, unsupported, and suspicious result.

The report must account for every company and state whether normal scanning may continue for healthy sources.

### Manual work

- Reproduce several failures from diagnostics.
- Inspect saved evidence for sensitive data.
- Review one LLM repair proposal.
- Test the proposed repair against fixtures and a live sample.
- Approve or reject the repair manually.
- Confirm previous working configuration remains recoverable.

### CONDITIONAL STOP — Human checkpoint H11: approve a live repair

Synthetic repair-workflow tests do not require approval. Trigger this checkpoint before activating any LLM-proposed change to the real company registry, adapter configuration, or source logic.

The agent must provide a stable proposal ID, the observed failure, sanitized evidence, exact diff, confidence, affected companies, fixture and live-test results, rollback instructions, and its recommendation. Ask the user to reply `approve <proposal-id>` or `reject <proposal-id>` with optional notes.

Do not interpret general permission to continue as repair approval, and never allow the repair system to edit active configuration directly. After explicit approval, apply the exact reviewed diff through the normal code or configuration workflow, rerun affected adapter-group tests, commit it as a focused repair, and confirm rollback remains possible. If rejected, record the disposition and leave active configuration unchanged.

### Completion gate

Phase 10 is complete when every known failure class is visible and actionable, failures cannot corrupt state, and repair evidence can be reviewed independently.

### Commit sequence

1. `feat: add source anomaly detection`
2. `test: add source failure drills`
3. `feat: add targeted source verification`
4. `feat: add sanitized diagnostic reports`
5. `feat: add guarded source repair proposals`

### Stop conditions

Stop before Phase 11 if:

- A broken source can still appear healthy.
- Diagnostics expose credentials or cookies.
- A repair proposal can change active configuration without approval.

## Phase 11 Full-registry pilot

### Objective

Prove that the manual tool remains useful and stable across repeated real scans before considering scheduling or notifications.

### Prerequisites

- All earlier phase gates pass.
- Release-candidate registry and search profile are reviewed.
- Known unsupported and blocked sources are documented.

### Deliverables

- Release-candidate configuration snapshot.
- Repeated-run pilot log.
- Defect and regression-test history.
- Coverage summary.
- Quality summary.
- Operating runbook.
- Known limitations.
- Release decision.

### Pilot procedure

1. Record registry, profile, schema, prompt, and adapter versions.
2. Start from a deliberate baseline or documented existing state.
3. Run the scan on several different days.
4. Do not reset duplicate state between normal pilot runs.
5. Review every new match during the initial runs.
6. Sample deterministic rejections.
7. Review all uncertain dates and seniority results.
8. Review all source failures.
9. Record scan duration, request volume, and LLM usage.
10. Convert defects into fixtures or deterministic examples.
11. Fix one meaningful defect at a time.
12. Run focused tests and the required company gate.
13. Commit each fix.
14. Repeat the full-registry scan after fixes.

### STOP — Human checkpoint H12: continue the multi-day pilot

A same-day rerun is useful for duplicate testing but does not count as a different-day pilot run. The agent must not alter the clock, publication dates, or state to simulate the passage of time.

After each clean pilot run, the agent must update and commit the pilot log, state which calendar dates have been covered, summarize matches and unresolved issues, and say whether another different-day run is still required. If so, ask the user to return on a later day and say `run the next pilot scan`. Then stop.

When the user returns, preserve duplicate state, verify the current date and configuration versions, run the next scan, and repeat this checkpoint. If defects are found, fix and commit them normally, but do not count a synthetic or reset run as evidence of multi-day stability.

### Pilot log fields

- Run ID and time.
- Registry and profile versions.
- Companies attempted and successful.
- Source exceptions.
- Listings fetched.
- Recent listings.
- Role and location candidates.
- New identities.
- LLM calls and cache hits.
- Matches, rejections, and uncertainties.
- False positives.
- Known false negatives.
- Changes made afterward.

### Release metrics

| Metric | Release expectation |
|---|---|
| Registry accounting | Every company is successful, disabled, unsupported, blocked, or failed with a reason |
| Duplicate behavior | An unchanged immediate rerun displays no repeated job |
| Role and location quality | Reviewed samples show no unresolved systematic defect |
| Seniority quality | Reviewed evaluation set meets the approved threshold |
| Uncertainty | Date and seniority uncertainty remain visible |
| Failure visibility | No known broken source appears as a healthy empty result |
| Operability | A user can run the command and understand the report |
| Repository quality | Validation passes and meaningful changes have focused commits |

### Manual release review

- [ ] Review every unresolved source exception.
- [ ] Decide which exceptions block release.
- [ ] Confirm no temporary test values remain in the search profile.
- [ ] Confirm configuration contains no secrets.
- [ ] Back up and restore state.
- [ ] Run the final validation command.
- [ ] Run the final full-registry verification.
- [ ] Run the final manual scan.
- [ ] Review known limitations.
- [ ] Confirm Git status is clean except for known unrelated user files.

### STOP — Human checkpoint H13: approve the first release

Before stopping, the agent must provide a release-readiness summary with every metric, unresolved exception, known limitation, validation result, pilot dates, Git status, and proposed version tag. It must clearly recommend either release or further work.

Ask the user to choose one of:

- `approve release, create tag <proposed-tag>`
- `approve release, no tag`
- `do not release: <reason>`

Do not create a tag or describe the system as released without explicit approval. After approval, record the release decision, rerun the final validation if the working tree changed, commit the release documentation, and create only the specifically approved tag. If release is rejected, convert the reasons into tracked work and resume at the relevant phase.

### Completion gate

Phase 11 is complete when release metrics pass, limitations are explicit and acceptable, and the manual trigger is ready for regular use.

### Commit sequence

During the pilot:

```text
fix: <specific defect and behavior>
test: <regression case when separate>
data: <reviewed source correction>
```

At release readiness:

1. `data: finalize reviewed company source registry`
2. `docs: record manual scan pilot results`
3. `docs: add first-release operating instructions`
4. Create a version tag only after validation passes and the working tree is clean.

## Definition of done for the first release

- [ ] The fixed company list is completely accounted for.
- [ ] Every supported adapter has fixtures, tests, and documentation.
- [ ] Every adapter group has a recorded validation result.
- [ ] Every displayed job satisfies the recency, role, location, duplicate, and seniority rules or is clearly marked uncertain.
- [ ] Every displayed job has a direct URL.
- [ ] Every displayed job shows its date basis.
- [ ] Repeated unchanged scans do not display the same job again.
- [ ] Repeated unchanged scans do not repeat LLM calls.
- [ ] A failure on one company does not stop healthy companies.
- [ ] The report distinguishes no matches from incomplete coverage.
- [ ] State backup, restore, inspection, and reset work.
- [ ] A user can run the tool without reading code.
- [ ] No secret, local state, or transient report is committed.
- [ ] Automated validation passes.
- [ ] Full-registry verification passes or has approved documented exceptions.
- [ ] Every meaningful change appears in a focused Git commit.

## Manual decisions that must remain recorded

| Decision | When required | Evidence to retain |
|---|---|---|
| Source approval | After LLM-assisted discovery or repair | URL, reviewer, evidence, verification date |
| Date policy | When a source date meaning is uncertain | Field, interpretation, examples, confidence |
| Role vocabulary | After a concrete false positive or negative | Example title and rule change |
| Location policy | When remote, hybrid, or multi-location behavior is ambiguous | Example and accepted interpretation |
| Seniority expectation | Before LLM evaluation and after systematic disagreements | Reviewed examples and profile version |
| Unsupported source | When access controls, terms, or effort make automation unsuitable | Reason, fallback, revisit condition |
| Release exception | When a known issue does not block first release | Impact, workaround, approval, future action |

## Work deferred until after the first release

### Scheduling

Wrap the same manual command in an approved scheduler after the manual pipeline is reliable. Scheduling should not introduce new collection or matching logic.

### Notifications

Send the existing report through the selected channel. Notification failures should not change job-discovery state or create duplicate evaluations.

### Add Company workflow

Expose the source-discovery, adapter-selection, validation, and approval process through a user-facing command or interface.

### Full lifecycle tracking

Add updated, missing, closed, reopened, and reposted events only if those states become useful. Do not complicate the first-release duplicate model in anticipation of uncertain future needs.

### Automatic repair

Consider automatic application of low-risk configuration repairs only after repair proposals have a strong test history and rollback path. Adapter code changes should continue to require normal review and testing.

## Related documents

- [System Design](01_job_posting_discovery_system_design.md)
- [Implementation Guide](02_job_posting_discovery_implementation_guide.md)
