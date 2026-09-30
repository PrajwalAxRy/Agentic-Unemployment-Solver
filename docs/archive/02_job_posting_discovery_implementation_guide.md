> # ARCHIVED -- historical record, not current behaviour
>
> This documents the step-by-step build order.
>
> Largely a prose restatement of the phased execution plan beside it, and stale in the
> same places (Step 8 role filtering, Step 10 seniority evaluation). Kept only so the
> build narrative survives; nothing here is uniquely load-bearing.
>
> For how the system works today: **`CLAUDE.md`**.
> For what was decided and why: **`docs/decisions.md`**.

---

# Job Posting Discovery Implementation Guide

Version 1.0

Date: 20 September 2026

## Purpose

This guide explains how to build the job discovery system in small, human-reviewable steps. Each step should leave the project working. We will test a small representative sample while code is changing, then test the complete affected company group or the full company registry before moving forward.

The guiding rhythm is:

1. Decide what one step must prove.
2. Implement the smallest version that can prove it.
3. Test it with saved fixtures.
4. Test it against representative live companies.
5. Run the required adapter-group or full-company check.
6. Inspect the result manually.
7. Fix what the evidence shows.
8. Commit the completed change.
9. Move to the next step only after the completion gate passes.

This approach avoids building the full system before discovering that company sources, date fields, filters, or duplicate keys behave differently from our assumptions.

## How broad testing should work

Testing every company after every line of code would be slow and could create unnecessary traffic. Testing only a few companies until the end would allow systemic mistakes to spread. We will use three validation levels.

### Focused tests

Run these continuously while developing:

- Unit tests for pure rules and schemas.
- Saved-response fixture tests for adapters.
- One or two representative live companies.

### Adapter-group tests

Run these after any change to an adapter or its shared request behavior:

- Every company mapped to that adapter.
- Lightweight listing retrieval unless full details are specifically under test.
- Manual comparison for representative companies and every unexpected exception.

### Full-registry tests

Run these after a cross-cutting layer is completed:

- Source inventory.
- Shared normalization.
- Ten-day filtering.
- Role and location filtering.
- Duplicate mapping.
- Manual trigger and report.
- Final resilience work.

The full-registry test should use the least expensive operation that proves the layer. We should not download every description or call the LLM when testing a layer that only concerns source configuration or listing normalization.

## Git rule

Commit after every meaningful completed change. A meaningful change is one coherent feature, adapter, configuration batch, migration, bug fix, or documentation update that can be reviewed and reverted independently.

Before committing:

- Run the focused tests for the change.
- Run the adapter-group or full-registry gate required by the step.
- Inspect the staged diff.
- Confirm no secret, local database, transient report, or unrelated user file is staged.
- Update documentation if behavior changed.
- Write a commit message that describes the behavior delivered.

Do not combine unrelated adapters or fixes in one commit. Do not commit a partially working phase merely because a large amount of code has changed.

## Step 1 Prepare the repository

### What we are trying to prove

We can build and test the project repeatedly without mixing source code, configuration, generated reports, local state, and secrets.

### Build work

Create a simple project structure similar to:

```text
job-finder/
  src/
    job_finder/
      adapters/
      core/
      filters/
      matching/
      persistence/
      reporting/
  config/
  docs/
  tests/
    fixtures/
  reports/
  state/
```

Then:

1. Choose and document the supported Python version.
2. Add dependency management.
3. Add formatting, linting, type-checking, and test commands.
4. Create a single validation command that runs the agreed checks.
5. Add ignore rules for local databases, credentials, generated reports, temporary browser data, caches, and diagnostics.
6. Add a sample configuration that contains no real secret.
7. Add a minimal smoke test that imports the application package.

### Manual checks

- Open Git status and identify all pre-existing user files before staging anything.
- Run the validation command from a new shell.
- Create a temporary report and state database and verify both remain untracked.
- Confirm the existing company workbook is not accidentally moved, renamed, or staged.

### Done when

- A clean checkout can install and run the validation command from documented instructions.
- Generated state and secrets cannot be committed accidentally under normal use.
- The repository starts from a known, clean structure.

### Commit

Suggested commit:

```text
chore: scaffold job discovery project
```

If validation tooling is a substantial independent change, commit it separately:

```text
test: add project validation commands
```

## Step 2 Write the search profile before writing adapters

### What we are trying to prove

The team agrees on what should pass before source behavior starts influencing the definition.

### Build work

Create a versioned search-profile configuration with:

- Target role families.
- Accepted title synonyms.
- Title exclusions.
- Accepted cities, regions, and countries.
- Remote and hybrid policy.
- Seniority target written in plain language.
- Ten-day recency window.
- A `measure_then_decide` mode that holds uncertain publication dates separately until Phase 5 coverage is reviewed.

The final uncertain-date inclusion policy is intentionally deferred. Use the approved baseline in [Approved Product Decisions](../04_product_decisions.md); do not choose a strict or permissive default during this step.

Create examples for every rule. Examples should include easy cases and cases likely to produce mistakes.

Example role cases:

| Title | Expected result | Reason |
|---|---|---|
| Senior Machine Learning Engineer | Role pass | Accepted role family |
| AI Infrastructure Engineer | Role pass if included in the profile | Accepted synonym |
| AI Sales Engineer | Role fail | Explicit exclusion |
| Software Engineer | Depends on agreed role breadth | Requires a deliberate rule |

Example location cases should cover:

- City aliases.
- Multiple listed cities.
- Country-only locations.
- Remote within a restricted country.
- Hybrid wording.
- Location missing or ambiguous.

### Manual checks

- Review real titles from the existing company list or career pages.
- Ask whether a human can classify each example without asking what the rule means.
- Resolve ambiguous role families now rather than adding source-specific exceptions later.
- Review the seniority description separately from role and location.

### Tests

- Schema accepts the intended profile.
- Missing required fields produce useful messages.
- Every approved example has an automated expected result once filters are implemented.
- Profile version changes produce a different deterministic hash.

### Done when

The profile is specific enough that role and location decisions can be implemented deterministically, while seniority remains a clearly defined LLM task.

### Commit

```text
docs: define job search profile and recency policy
```

## Step 3 Inventory every company source

### What we are trying to prove

Every company in the fixed list is accounted for and can be assigned to a reusable adapter family or an explicit unsupported category.

### Build work

Create a company-source registry with a stable `company_id`. Use an LLM-assisted research process to propose:

- Official careers URL.
- Region or country board if relevant.
- ATS or source family.
- Board token, tenant, site slug, locale, or search parameters.
- Complete-list or search-only behavior.
- Likely job ID field.
- Likely publication-date field.
- Detail-fetch behavior.
- Confidence.
- Evidence.

Add a registry validator that checks:

- Duplicate company IDs.
- Missing company names.
- Invalid or missing official URLs.
- Unknown adapter types.
- Missing parameters required by the selected adapter.
- Enabled companies with unresolved low-confidence configuration.

### Work through the list in manageable batches

1. Process a batch of companies with the LLM-assisted discovery prompt.
2. Review every low-confidence proposal.
3. Correct obvious regional-board and official-link mistakes.
4. Add the reviewed batch to the registry.
5. Run registry validation.
6. Commit the batch if it is large enough to be independently reviewable.

Do not wait until every company has been researched before preserving validated work. Do not commit an unreviewed LLM output dump as if it were approved configuration.

### Full-company test

After all batches are complete:

- Every company from the input list must appear exactly once.
- Every enabled company must have a verified official URL.
- Every enabled company must have an adapter family or an explicit custom-source requirement.
- Every unsupported or blocked source must include a reason.
- Every low-confidence source must be manually reviewed.

Create a coverage summary by adapter. This summary decides the adapter implementation order.

### Manual checks

- Open every low-confidence source in a browser.
- Check global companies for separate India or regional career boards.
- Remove job aggregators and recruiter copies.
- Select two or three representative companies from each adapter family.
- Select boards with different listing sizes where possible.

### Done when

The registry explains where every company belongs and the adapter backlog shows how much of the company list each adapter will cover.

### Commits

```text
feat: add company source registry validation
data: add verified company source inventory batch
data: complete company source inventory
```

Use separate inventory commits when the list is large enough that one commit would be difficult to review.

## Step 4 Define the shared contracts

### What we are trying to prove

All source adapters can target one consistent internal model, including successful, empty, partial, blocked, and failed outcomes.

### Build work

Define:

1. Company source configuration schema.
2. Normalized job record.
3. Adapter interface.
4. Adapter result and diagnostic structure.
5. Date-basis vocabulary.
6. Search-profile versioning.

The adapter interface should support:

- Listing retrieval.
- Pagination.
- Optional detail retrieval.
- Source verification without changing job state.
- Health metadata.

Create fake adapters and fixtures for:

- Healthy listings.
- A valid empty board.
- Malformed data.
- A login page returned as HTML.
- A blocked page.
- Incomplete pagination.

### Tests

- Invalid source configuration is rejected before network access.
- Normalized jobs require company, title, location, and canonical URL.
- A valid empty board differs from a parse failure.
- Partial or suspicious data cannot be reported as a normal complete result.
- Unknown schema versions follow the declared compatibility policy.

### Manual checks

- Read the schemas as if implementing a new adapter.
- Confirm that the adapter contract contains no field specific to only one ATS.
- Confirm diagnostic fields are sufficient to explain failures later.

### Done when

A fake adapter can produce normalized jobs and health diagnostics through the same interface planned for every real source.

### Commits

```text
feat: add company source and job schemas
feat: define adapter and diagnostic contracts
test: add core contract fixtures
```

## Step 5 Build the first adapter end to end

### What we are trying to prove

One high-coverage structured ATS can move from saved response to normalized live listings using the shared contracts.

### Choose the first adapter

Select the adapter that combines:

- High company coverage.
- Public structured listings.
- Stable identity fields.
- Clear pagination.
- Reasonable documentation or observable behavior.

### Build work

1. Save representative response fixtures.
2. Write parser tests against fixtures.
3. Implement listing retrieval.
4. Implement pagination.
5. Map identity, title, location, date evidence, URL, and description availability.
6. Add bounded timeouts and retries.
7. Add source-specific validation.
8. Add optional detail retrieval only if required.
9. Add a verification command that does not modify duplicate state.

### Focused tests

- Healthy fixture returns expected records.
- Pagination returns all pages without duplicates.
- Empty fixture returns a healthy empty result.
- Malformed fixture fails visibly.
- Redirect and access-block fixtures are not parsed as jobs.
- Identity and canonical URLs remain stable across runs.

### Representative live checks

For two or three selected companies:

- Compare visible job count with fetched count.
- Open several returned URLs.
- Verify title and location.
- Verify the date field means what the adapter claims.
- Verify whether list data already includes the description.

### Test all companies in this adapter family

Run the lightweight verification command for every mapped company. Every company must either:

- Return valid normalized listings.
- Return a valid empty listing.
- Return a precise reviewed exception.

Investigate unexpected zero results and count collapses. Do not add one-off parsing logic until determining whether the problem is configuration or shared adapter behavior.

### Done when

Every valid company in the adapter family works through the shared interface or has a documented reviewed exception.

### Commits

```text
feat: add shared HTTP client and adapter base
test: add first ATS response fixtures
feat: add first ATS listing adapter
data: correct first ATS company mappings
```

Keep configuration corrections separate from adapter code when that improves reviewability.

## Step 6 Add the remaining adapter families

### What we are trying to prove

The reusable adapter set covers the approved first-release company scope.

### Repeat this work package for each adapter

1. Document required configuration parameters.
2. Capture healthy, empty, malformed, and blocked fixtures.
3. Implement listing and pagination.
4. Implement identity, title, location, date, and URL mapping.
5. Implement detail retrieval when required.
6. Add adapter-specific validation and diagnostics.
7. Run fixture tests.
8. Run representative live checks.
9. Run the complete adapter-group test.
10. Correct reviewed configuration errors.
11. Commit the adapter.

### Important discipline

- Implement one adapter at a time.
- Do not put two unrelated adapters in one commit.
- Fix shared client or normalization behavior in a separate commit when several adapters are affected.
- Preserve a fixture that reproduces every parser bug before fixing it.
- Do not bypass authentication, CAPTCHA, or access controls.

### Full-registry checkpoint

After the planned adapter set is complete, run listing verification across every enabled company.

Reconcile:

- Total companies in the registry.
- Enabled companies.
- Successful companies.
- Valid empty boards.
- Unsupported sources.
- Blocked sources.
- Failed sources.

The totals must account for the complete enabled registry. No company should disappear from the summary.

### Done when

The approved first-release scope has reusable adapters and every excluded source has a reason and fallback.

### Commit pattern

```text
test: add lever response fixtures
feat: add lever listing adapter
data: verify lever company mappings
```

Repeat the pattern for each adapter.

## Step 7 Add shared normalization and the ten-day rule

### What we are trying to prove

Jobs from different sources can be compared consistently, and every recency decision states its evidence.

### Build work

Implement shared normalization for:

- Whitespace and safe case folding.
- Title punctuation and aliases.
- Location aliases and multi-location values.
- Canonical URLs.
- Timezone-aware timestamps.
- Date basis.
- Plain-text descriptions.

Implement the rolling ten-day rule against an explicit scan time.

Do not discard the original source values. Store original and normalized values side by side.

### Tests

- Exactly ten days old.
- Just inside ten days.
- Just outside ten days.
- Date-only values.
- Timezone boundary cases.
- Malformed and future timestamps.
- Updated timestamp treated as uncertain.
- Tracking parameters removed without losing identity parameters.
- Multi-location normalization.

### Full-company test

Run all enabled companies through listing and normalization. Do not call the LLM.

Review metrics by adapter:

- Listings fetched.
- Listings with reliable publication dates.
- Listings with uncertain dates.
- Listings inside ten days.
- Listings outside ten days.
- Listings with invalid dates.

Also produce a full-registry date-coverage report containing:

- Total enabled companies.
- Companies with reliable publication dates for every observed listing.
- Companies with mixed reliable and uncertain dates.
- Companies whose observed listings have no reliable publication dates.
- Companies with no listings or that could not be assessed, kept separate from date failures.
- Total listings with reliable, uncertain, invalid, and missing dates.
- Percentages by company and by listing.
- The same breakdown by adapter or source family.
- `first_seen` availability and representative source evidence.

### Manual checks

- Open accepted, rejected, and uncertain examples from every adapter.
- Compare visible source dates with normalized dates.
- Investigate adapters with unusually high date uncertainty.
- Promote a date field to reliable only when evidence supports it.

### Human checkpoint

Present the date-coverage report, affected companies, representative URLs and date labels, and a recommendation. Then stop and ask the user to choose whether uncertain-date jobs should be excluded, shown separately, handled using forward-only `first_seen`, or governed by an adapter-specific hybrid policy. Do not choose automatically. After the response, record the decision in configuration and documentation, add tests, and rerun the recency report.

### Done when

Every normalized job has a stable identity candidate, canonical URL, and explicit date basis; the user-approved uncertain-date policy is recorded and tested; and the ten-day rule behaves consistently across sources and timezones.

### Commits

```text
feat: normalize job titles locations and URLs
feat: normalize publication dates and date basis
feat: apply rolling ten-day recency policy
```

## Step 8 Add role and location filtering

### What we are trying to prove

The deterministic filters reduce recent listings to a manageable candidate set without systematic omissions.

### Build work

Implement:

- Role-family matching.
- Title synonyms.
- Title exclusions.
- Location aliases.
- Remote and hybrid policy.
- Multi-location behavior.
- Machine-readable pass and rejection reasons.
- Search-profile hash and version.

Portal-side search can still reduce data volume, but the local filters make the final decision.

### Focused tests

Run every example created in Step 2. Add a regression example whenever a real job exposes a mistake.

### Full-company test

Run all recent normalized listings through role and location filters.

Produce:

- Count before filters.
- Count after role filter.
- Count after location filter.
- Rejection counts by reason.
- Retained samples grouped by role family and location.

### Manual checks

- Review at least twenty retained jobs or the complete retained set if smaller.
- Review at least twenty rejected jobs across all rejection reasons.
- Inspect companies with zero retained jobs.
- Confirm broad synonyms are not admitting unrelated roles.
- Confirm exclusions are not removing legitimate target jobs.

### Done when

The retained set is small enough for description retrieval and manual review finds no systematic role or location defect.

### Commits

```text
feat: add role-family title filtering
feat: add location and work-mode filtering
test: add live filter regression examples
```

## Step 9 Add duplicate persistence

### What we are trying to prove

Repeated manual scans process each job once unless its description or evaluation inputs meaningfully change.

### Build work

Create a local database with:

- Job key.
- External ID when available.
- Canonical URL.
- Fallback fingerprint.
- First-seen and last-seen timestamps.
- Description hash.
- Search-profile version.
- Prompt version.
- Evaluation status and result.

Implement identity priority:

1. External source job ID.
2. Canonical URL.
3. Fallback normalized fingerprint.

Add:

- Transactional writes.
- Pending evaluation recovery.
- Backup command.
- Deliberate reset command.
- Inspection command.
- Concurrency lock.

### Tests

- Same fixture scan twice produces zero unseen jobs on the second run.
- Tracking parameters do not change identity.
- Separate requisition IDs remain separate even with identical titles.
- Description changes invalidate the cached evaluation without creating a new job identity.
- Interrupted work remains pending and resumes.
- Concurrent scan attempts fail or serialize clearly.

### Full-company test

1. Run the complete lightweight pipeline from a fresh state.
2. Record observed and unseen counts.
3. Run it again immediately.
4. Investigate every unexplained unseen job in the second run.

### Manual checks

- Review fallback fingerprints for accidental merges.
- Back up and restore the database once.
- Confirm the database and backup are ignored by Git.
- Confirm reset requires a deliberate command rather than deleting an unknown file.

### Done when

Repeated unchanged scans are idempotent and state can be inspected, backed up, restored, and reset through documented commands.

### Commits

```text
feat: add job state database and migrations
feat: add stable job identity mapping
feat: suppress previously processed jobs
feat: add state backup and reset commands
```

## Step 10 Add LLM seniority evaluation

### What we are trying to prove

The system can interpret seniority from descriptions using structured, explainable, cached decisions.

### Build work

1. Define the seniority taxonomy.
2. Define the response schema.
3. Write a versioned prompt.
4. Require evidence from the description.
5. Validate every response.
6. Retry one malformed response.
7. Route continued failures and uncertain decisions to manual review.
8. Cache by job identity, description hash, profile version, prompt version, and model policy.
9. Record request usage.
10. Add an upper limit on jobs evaluated in one run.

### Create a reviewed evaluation set

Include descriptions with:

- Explicit years of experience.
- Entry-level language without years.
- Senior title but mid-level description.
- Junior title but unexpectedly advanced ownership.
- Staff or principal scope.
- Management requirements.
- Conflicting indicators.
- No usable seniority evidence.

Each example should have a human-approved expected result and short rationale.

### Tests

- Valid responses pass schema validation.
- Malformed responses retry once.
- Repeated invalid responses become manual-review items.
- Cached decisions prevent repeated calls.
- Description or profile changes invalidate the cache.
- Old, role-rejected, location-rejected, and already evaluated jobs never call the LLM.

### Limited live test

Run a small batch of unseen filtered candidates. Review every result manually.

Record:

- Correct match.
- Correct rejection.
- Acceptable uncertainty.
- False acceptance.
- False rejection.
- Missing evidence.
- Schema or service failure.

Improve the shared prompt or profile using regression examples. Do not create company-specific seniority prompts.

### Full-company checkpoint

Run all companies through deterministic filters. Call the LLM only for unseen surviving candidates. Review:

- Number of candidates reaching the LLM.
- Cache hit rate.
- Match, reject, and uncertain counts.
- Request usage.
- All uncertain decisions.
- A sample of matches and rejections.

### Done when

The reviewed evaluation set meets the approved quality threshold, every decision includes evidence, and repeated runs use cached decisions.

### Commits

```text
feat: define seniority evaluation schema
test: add reviewed seniority evaluation set
feat: add versioned LLM seniority evaluator
feat: cache seniority decisions
```

Prompt refinements should have their own commits when they change behavior materially.

## Step 11 Build the manual trigger and report

### What we are trying to prove

A user can run one command and understand the result without reading source code.

### Build work

Create one command such as:

```text
job-finder scan
```

The command should:

- Load and validate configuration.
- State which profile and registry versions are in use.
- Prevent overlapping state writes.
- Show useful progress without excessive output.
- Process healthy sources even if another source fails.
- Persist run metrics.
- Produce a human-readable report.
- Produce machine-readable JSON for automated tests.
- Return an appropriate exit status.

The report should contain:

1. Run summary and coverage.
2. New matching jobs.
3. Date-uncertain candidates.
4. Seniority-review candidates.
5. Source failures.

Zero matching jobs is a successful outcome when coverage is complete. The report should say so explicitly.

### End-to-end tests

- Healthy run with matches.
- Healthy run with no matches.
- Partial source failure with healthy results preserved.
- Complete run failure.
- Date-uncertain candidate.
- Seniority-uncertain candidate.
- Second unchanged run with no duplicate output.

### Full-company test

Run the complete registry from a fresh state, then run it again.

Reconcile:

- Companies attempted.
- Companies successful.
- Companies failed, blocked, unsupported, or disabled.
- Recent listings.
- Role and location candidates.
- Unseen candidates.
- LLM matches and uncertainties.
- Duplicate suppression on the second run.

### Human usability test

Ask someone who did not write the command to:

1. Follow the run instructions.
2. Start a scan.
3. Identify whether coverage was complete.
4. Open several matching jobs.
5. Explain why each job was included.
6. Identify sources needing attention.

Revise wording that requires implementation knowledge.

### Done when

A nondeveloper can run the scan, understand the report, and distinguish no matches from incomplete coverage.

### Commits

```text
feat: add manual job scan command
feat: add job discovery report
docs: add scan runbook and troubleshooting guide
```

## Step 12 Harden failure handling

### What we are trying to prove

The system does not silently omit companies and leaves actionable evidence when a source breaks.

### Build work

Add:

- Bounded retries and backoff.
- Rate-limit handling.
- Redirect validation.
- Login and CAPTCHA detection.
- Required-field checks.
- Result-count anomaly checks.
- Pagination-loop protection.
- Sanitized diagnostics.
- One-company, adapter-group, and full-registry verification commands.
- LLM-assisted repair proposal generation that does not auto-apply changes.

### Failure drills

- Return a login page with status 200.
- Remove a required JSON field.
- Repeat a pagination cursor.
- Simulate a timeout.
- Simulate a rate limit.
- Return zero jobs for a historically large board.
- Break one company while the others remain healthy.

### Full-company test

Run verification against every enabled company. Review every failed, blocked, unsupported, and suspicious source.

For each exception, decide whether it is:

- Temporary availability.
- Incorrect company configuration.
- Adapter defect.
- Source redesign.
- Access restriction.
- Unsupported source.

### Manual checks

- Confirm diagnostics contain enough evidence for another person to reproduce the issue.
- Confirm diagnostics do not contain credentials or sensitive cookies.
- Test one repair proposal through fixtures and a live sample without changing active configuration automatically.

### Done when

Every failure is visible, categorized, and contained. No failed or suspicious source is reported as a healthy empty board.

### Commits

```text
feat: add source health and anomaly checks
test: add source failure drills
feat: add source verification command
feat: add guarded source repair proposals
```

## Step 13 Run a full-registry pilot

### What we are trying to prove

The tool remains useful across repeated real manual runs before scheduling or notifications are added.

### Pilot procedure

1. Freeze a release-candidate registry and search-profile version.
2. Start from a deliberate baseline or documented existing state.
3. Run several manual scans on different days.
4. Review every displayed match during the first pilot runs.
5. Sample deterministic rejections.
6. Record source failures and date uncertainty.
7. Record LLM disagreements.
8. Measure scan duration, request volume, and LLM usage.
9. Fix defects with regression tests and focused commits.
10. Repeat the full-registry scan after fixes.

### Pilot log

For each run, capture:

- Registry and profile versions.
- Company coverage.
- Source failures.
- Listings found.
- Listings inside ten days.
- Role and location candidates.
- New identities.
- LLM calls and cached decisions.
- Matches and uncertainties.
- False positives and known false negatives.
- Follow-up changes.

Do not commit transient job reports containing live results unless there is a deliberate reason. Commit the summarized findings and reproducible test cases instead.

### Done when

- Every company is accounted for.
- Repeated unchanged scans do not show duplicates.
- Role and location samples show no unresolved systematic defect.
- Seniority evaluation meets the approved threshold.
- Broken sources cannot hide as empty results.
- A user can run and understand the tool.
- Remaining limitations are explicit and accepted.

### Commits

Commit each pilot defect separately after its regression test and required company checks pass.

Then commit release evidence:

```text
docs: record manual scan pilot results
data: finalize reviewed source registry
docs: add first-release operating instructions
```

Tag a release only after the final validation command passes and Git status is clean.

## Definition of done for every meaningful change

- [ ] The change has one clear purpose.
- [ ] Focused automated tests pass.
- [ ] Required fixture tests pass.
- [ ] Required representative live checks pass.
- [ ] Required adapter-group or full-registry test passes, or reviewed exceptions are documented.
- [ ] Manual review confirms the output matches visible source behavior.
- [ ] Failure behavior is tested when the change introduces an external dependency.
- [ ] Documentation and examples reflect the behavior.
- [ ] No secret, state database, generated report, or unrelated user file is staged.
- [ ] The staged diff contains only the meaningful change.
- [ ] The commit message describes the delivered behavior.

## Commit message patterns

Examples:

```text
feat: add greenhouse listing adapter
feat: match approved India locations
feat: suppress repeated job identities
feat: evaluate seniority from job descriptions
fix: reject workday login page as job data
data: verify ashby company mappings
test: cover pagination cursor loops
docs: explain date uncertainty handling
```

## When to stop and review instead of continuing

Stop the step and investigate when:

- A full-company count does not reconcile.
- A source returns zero jobs unexpectedly.
- An adapter works only after adding company-specific parsing branches.
- Publication dates have inconsistent meanings within one adapter family.
- Role or location filtering produces an unexpectedly large or empty set.
- A second unchanged run produces unexplained new identities.
- The LLM is called for candidates that should have been rejected earlier.
- LLM results lack evidence or change unpredictably for unchanged inputs.
- A healthy source failure is hidden in the overall success summary.
- A commit would include unrelated files or failing tests.

The purpose of the gates is to stop uncertainty from becoming the foundation of the next layer.

## Related documents

- [System Design](01_job_posting_discovery_system_design.md)
- [Phased Execution Plan](03_job_posting_discovery_phased_execution_plan.md)
- [Approved Product Decisions](../04_product_decisions.md)
