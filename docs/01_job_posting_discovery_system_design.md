# Job Posting Discovery System Design

Version 1.0

Date: 20 September 2026

## Purpose

This document records the agreed design for a manually triggered job discovery system built around a fixed list of companies. The first release will search recent job postings, apply consistent role and location filters, use an LLM to assess seniority from each surviving job description, suppress duplicates, and return a useful report.

The design deliberately separates two kinds of work:

1. **Source discovery and repair**, where an LLM helps us determine how a company publishes jobs and proposes the correct configuration.
2. **Routine scanning**, where deterministic code uses saved, tested configuration so results are repeatable and failures are visible.

The system will not schedule itself or send notifications in the first release. A user will explicitly trigger each scan.

## Agreed product behavior

When the user triggers a scan, the system should:

1. Read the configured company list.
2. Fetch current job listings from each enabled company source.
3. Normalize source-specific job fields into one internal format.
4. Keep postings that fall within a rolling ten-day window, using a clearly stated date basis.
5. Filter those postings by target role and accepted location.
6. Suppress jobs already processed in an earlier scan.
7. Retrieve the full description only for unseen candidates that passed the earlier filters.
8. Ask an LLM to decide whether the seniority described in the posting fits the target profile.
9. Store the job identity and evaluation so later runs remain idempotent.
10. Display new matching jobs and a summary of sources that could not be checked.

The user-facing question is:

> What relevant jobs have appeared recently that I have not already seen?

## Goals for the first release

- Run only when the user explicitly requests a scan.
- Use the existing fixed company list as the source registry.
- Focus on postings from a rolling ten-day window.
- Filter deterministically by role and location.
- Interpret seniority from the full description with an LLM.
- Avoid showing the same posting on repeated scans.
- Use reusable source adapters instead of one scraper per company.
- Report partial coverage and source failures rather than hiding them.
- Keep enough diagnostics to investigate source breakage later.
- Preserve a path to scheduling, notifications, and easier company onboarding without redesigning the core pipeline.

## Excluded from the first release

The following capabilities are intentionally deferred:

- Scheduled execution.
- ChatGPT, Outlook, Teams, or mobile notifications.
- Automatic job applications.
- Resume or cover-letter generation.
- Tracking when a job closes, reopens, or changes after it was processed.
- Compensation filtering.
- Skills-based semantic ranking beyond the agreed role, location, and seniority logic.
- Fully automatic repair of broken sources.
- Fully automatic onboarding of a new company without validation and approval.

These are possible extensions, not prerequisites for a useful first release.

## System boundaries

| Area | First release | Possible later extension |
|---|---|---|
| Trigger | User manually starts a scan | Scheduled or event-driven scans |
| Time window | Rolling ten-day publication window | Configurable time windows |
| Deterministic filters | Role and location | Skills, compensation, company priority |
| LLM use | Seniority evaluation and source onboarding support | Broader ranking and assisted repair |
| Duplicate handling | Suppress previously processed job identities | Cross-source canonical matching and lifecycle events |
| Output | New matches, uncertain cases, and source failures | Email, chat, or mobile notifications |
| Company onboarding | Development-time LLM-assisted configuration | User-facing Add Company workflow |

## Architecture

### LLM-assisted control layer

The control layer is used when a source is first added or when it breaks. An LLM or browser-capable agent can:

- Locate the official company careers page.
- Distinguish the official page from aggregators, recruiter copies, and outdated links.
- Detect the applicant tracking system or source family.
- Identify public listing and detail access patterns.
- Determine pagination, publication-date fields, location fields, and job identity fields.
- Select a reusable adapter.
- Propose company-specific adapter parameters.
- Explain why a source failed and propose a repair.

The LLM should produce a proposed configuration with evidence and confidence. It should not silently change production configuration in the first release.

### Deterministic runtime layer

Every normal scan uses saved configuration and code. The runtime layer is responsible for:

- Loading and validating configuration.
- Fetching source data.
- Normalizing fields.
- Applying the ten-day rule.
- Filtering by role and location.
- Suppressing duplicates.
- Fetching descriptions.
- Calling the seniority evaluator.
- Persisting results.
- Producing the report.

This division keeps routine scans faster, cheaper, easier to test, and easier to diagnose than an approach where an LLM rediscovers every website during every run.

## Source adapter strategy

We should not build separate logic for every company. Most companies use a limited set of applicant tracking systems. We should build one adapter for each portal family and supply company-specific parameters through configuration.

Expected adapter families include:

- Greenhouse
- Lever
- Ashby
- Workday
- SmartRecruiters
- Other structured ATS platforms discovered in the company inventory
- Generic structured pages using embedded job data
- Search-only portals
- Custom career sites when no reusable adapter applies

For example, twenty Greenhouse companies should use one Greenhouse adapter with twenty different board identifiers.

### Preferred source methods

| Source type | Preferred method | Fallback |
|---|---|---|
| Public ATS API | Fetch structured listings and use the external job ID | Use the canonical hosted job URL |
| Structured career page | Read embedded JSON or JobPosting data | Use a conservative HTML parser |
| Search-only portal | Execute controlled role and location queries with verified pagination | Use a native employer alert if automation is prohibited |
| Custom portal | Build a narrow adapter with saved fixtures | Keep the source disabled until reviewed |

### Local filtering versus portal filtering

Whenever a source exposes a complete public listing, the system should fetch that listing and apply role and location rules locally. Portal search parameters may reduce network traffic, but they should not determine correctness because each portal interprets keywords and locations differently.

Portal-side filtering is acceptable as an optimization when:

- The source has a very large listing.
- The source exposes only search results.
- Pagination has been verified.
- Local filtering still makes the final eligibility decision.

## Company source registry

Every company needs a stable source record. The registry can begin in a structured worksheet, CSV, YAML, or JSON file, but it must be validated before scanning.

Recommended fields:

| Field | Purpose |
|---|---|
| `company_id` | Stable identifier independent of display-name changes |
| `company_name` | Name shown in reports |
| `careers_url` | Verified official careers or job-board URL |
| `adapter_type` | Reusable connector selected for the source |
| `adapter_parameters` | Board token, tenant, site slug, locale, or search settings |
| `identity_strategy` | Preferred job identity field |
| `date_strategy` | Publication field and confidence rule |
| `detail_strategy` | Whether descriptions require additional requests |
| `enabled` | Allows a source to be paused without deleting it |
| `confidence` | Confidence in the source classification |
| `evidence` | Evidence used to approve the configuration |
| `last_verified_at` | Most recent successful configuration check |
| `notes` | Known source-specific limitations |

Company names alone are not enough. The runtime needs the correct official URL and adapter parameters to avoid searching for the source repeatedly.

## LLM-assisted company onboarding

During development, the LLM-assisted discovery workflow should process each company as follows:

1. Locate the official careers page.
2. Verify that the page belongs to the intended company and region.
3. Detect the ATS or structured source.
4. Determine whether a complete list, a search interface, embedded data, or custom HTML is available.
5. Identify pagination and detail-fetch behavior.
6. Identify the best job ID, URL, publication date, title, and location fields.
7. Select an existing adapter when possible.
8. Produce the required adapter parameters.
9. Fetch a small sample and map it to the normalized job record.
10. Assign a confidence level and preserve evidence.
11. Run configuration and adapter validation.
12. Require human approval before enabling uncertain or custom sources.

If no existing adapter works, the company should be marked as requiring a custom adapter. It should not receive improvised runtime behavior that has not been tested.

## Normalized job record

Every adapter should produce the same internal record.

| Field | Meaning | Requirement |
|---|---|---|
| `company_id` | Company registry key | Required |
| `source_type` | Adapter or portal family | Required |
| `external_job_id` | Stable source job identifier | Preferred |
| `title_original` | Title as published | Required |
| `title_normalized` | Normalized title used for filtering | Required |
| `location_original` | Location as published | Required |
| `location_normalized` | Normalized locations used for filtering | Required |
| `published_at` | Source publication timestamp | Preferred |
| `date_basis` | `published`, `updated`, `first_seen`, or `unknown` | Required |
| `canonical_url` | Job URL without tracking parameters | Required |
| `description` | Normalized full description | Required before LLM evaluation |
| `description_hash` | Fingerprint used to reuse or invalidate an evaluation | Required after detail retrieval |
| `source_metadata` | Adapter-specific diagnostic metadata | Optional but useful |

Adapters should preserve original values as well as normalized values. Original values help with debugging and reporting, while normalized values support consistent rules.

## Ten-day recency policy

The recency window is a rolling interval measured from the scan timestamp. The system should not reset state at midnight or decide that a job is new merely because the calendar date changed.

### Date evidence rules

| Date evidence | Treatment |
|---|---|
| Reliable first-publication timestamp | Include when it falls inside the ten-day interval |
| Only an updated timestamp | Treat as uncertain unless the adapter has verified that it represents first publication |
| No source date after monitoring has begun | Use `first_seen_at` for later scans and label the basis |
| No usable date on the first scan | Put in a date-uncertain section or exclude in strict mode |

Every displayed job should show the date and date basis. The system must not present an update date as an original publication date unless that interpretation has been validated for the source.

## Role filtering

Role filtering should operate on normalized titles before any LLM request.

The search profile should define:

- Target role families.
- Accepted title synonyms.
- Common spelling and abbreviation variants.
- Explicit title exclusions.
- Precedence rules when a title contains both accepted and excluded terms.

A posting passes when its normalized title belongs to an accepted role family and no exclusion rule takes precedence.

The filter should return a reason such as:

- `accepted role family machine learning engineering`
- `rejected excluded title sales engineer`
- `rejected no target role family`

Filter reasons make false positives and false negatives easier to correct.

## Location filtering

Location filtering should also run before the LLM. The search profile should define:

- Accepted cities.
- City aliases.
- Accepted regions or countries.
- Remote-work policy.
- Hybrid-work policy.
- Treatment of postings with multiple locations.
- Treatment of location-ambiguous postings.

The system should preserve the original source location while comparing normalized tokens. Ambiguous multi-location postings can be retained with an uncertainty marker rather than discarded when one listed location may be acceptable.

## Duplicate mapping

The first release needs a small persistent store so the same recent posting does not reappear on every trigger.

### Job identity order

1. Use `company_id + source_type + external_job_id` when the source provides a stable identifier.
2. Otherwise use `company_id + canonical_url` after removing tracking parameters.
3. Otherwise build a fallback fingerprint from normalized company, title, location, and team or department.

The system should not merge two different requisitions merely because the title and location are the same. A stable source ID takes precedence over a similarity guess.

### Minimal state

The state store should retain:

- `job_key`
- `first_seen_at`
- `last_seen_at`
- `description_hash`
- `search_profile_version`
- `seniority_prompt_version`
- `seniority_result`
- `evaluation_status`

This is still a simple duplicate model. It does not require user-facing states such as closed, reopened, reposted, or missing.

### Idempotency rule

Running the same scan twice against unchanged sources should display zero additional new jobs and should not repeat LLM calls for unchanged descriptions and profiles.

If processing fails after a job is discovered but before seniority evaluation completes, the job should remain pending and be retried. It should not be permanently suppressed as if evaluation succeeded.

## LLM seniority evaluation

Only unseen candidates that pass recency, role, and location checks should reach the LLM.

The request should contain:

- The target seniority profile.
- The normalized job title.
- The normalized job description.
- Instructions to rely only on the description.
- A strict response schema.

Suggested response:

```json
{
  "seniority_match": true,
  "detected_level": "senior",
  "required_experience": "5 to 8 years",
  "evidence": "The role requires at least five years of relevant experience",
  "reason": "The required experience and ownership align with the target seniority"
}
```

Allowed `seniority_match` values should be `true`, `false`, or `uncertain`.

The system should validate every response. A malformed response may be retried once using the same prompt and model version. Continued failure should place the job in a manual-review section rather than silently accepting or rejecting it.

### Seniority caching

Reuse an evaluation only when all of the following remain unchanged:

- Job identity.
- Description hash.
- Search-profile version.
- Seniority-prompt version.
- Model policy, when model changes are treated as evaluation changes.

This prevents unnecessary cost while ensuring changed descriptions or requirements can be reevaluated.

## Error handling and source health

The runtime must distinguish a healthy empty board from a failed or incomplete source.

### Required checks

- HTTP status and content type.
- Unexpected redirects.
- Login, CAPTCHA, or access-block pages returned with status 200.
- Required fields.
- Pagination completion.
- Duplicate pages or cursor loops.
- Unexpected result-count collapse.
- Impossible or malformed dates.
- Schema changes.

### Failure behavior

| Failure | Automatic behavior | Report behavior |
|---|---|---|
| Timeout or rate limit | Retry with bounded backoff | Report if retries fail |
| Careers URL changed | Preserve existing configuration and stop the source | Source needs review |
| Schema or parser change | Save sanitized diagnostic evidence | Source needs adapter repair |
| CAPTCHA, login, or explicit block | Do not bypass the control | Mark blocked or use a native employer alert |
| Unexpected zero or count collapse | Mark the result suspicious | Source degraded, not healthy empty |
| LLM response failure | Retry once, then retain for review | Seniority uncertain |

One company failure should not stop healthy companies from returning results.

## Assisted repair workflow

When deterministic checks identify a broken source, the system can prepare a repair request for an LLM. The request should include:

- Company and source configuration.
- Adapter version.
- Sanitized failure details.
- Expected fields.
- Historical result-count context.
- A small response sample when policy permits.
- Existing fixtures and test expectations.

The LLM may propose:

- A changed company parameter.
- A new source URL.
- A changed field mapping.
- An adapter repair.
- A new custom adapter.
- A conclusion that the source should remain unsupported.

The proposal must be tested against fixtures and a live sample. Human approval is required before replacing the last known configuration in the first release.

## Manual scan report

Every manual trigger should return a report, including scans with no matching jobs.

Recommended report sections:

1. **Run summary**
   - Scan time and duration.
   - Company and search-profile versions.
   - Companies attempted, checked, failed, blocked, or unsupported.
2. **New matching jobs**
   - Company.
   - Role.
   - Location.
   - Publication date and date basis.
   - Seniority decision and evidence.
   - Direct job URL.
3. **Date-uncertain candidates**
   - Jobs that otherwise match but lack a trustworthy publication date.
4. **Seniority-review candidates**
   - Jobs for which the LLM returned `uncertain` or invalid output.
5. **Source failures**
   - Company.
   - Failure category.
   - Last successful verification if known.
   - Recommended next action.

The primary result should remain concise. Diagnostics belong in their own section rather than obscuring new matches.

## Security and responsible access

- Collect only public job information required for discovery.
- Respect site terms, robots guidance, rate limits, and explicit controls.
- Use conservative request frequency and a truthful client identity.
- Do not bypass login requirements, CAPTCHAs, or anti-automation controls.
- Keep API keys and credentials out of configuration committed to Git.
- Store secrets through environment or approved secret-management mechanisms.
- Sanitize saved diagnostic fixtures when they contain tokens, cookies, or personal data.
- Keep transient reports and the local state database out of Git.
- Record the access method and source URL so each adapter can be audited.

## Future Add Company workflow

A later user-facing workflow can be built on the development-time source-discovery process:

1. User supplies a company name or careers URL.
2. The LLM finds and verifies the official source.
3. The source family is detected.
4. An existing adapter is selected.
5. Adapter parameters are proposed.
6. Sample listings are fetched and normalized.
7. Configuration and adapter tests run.
8. The user reviews the evidence.
9. The company is enabled.

If no adapter fits, the company should be placed in a clearly identified custom-source queue instead of being partially added.

## Future extensions

| Extension | Foundation reused from the first release |
|---|---|
| Scheduled scans | Wrap the same manual scan command in a scheduler |
| Notifications | Send the existing report through the selected channel |
| Add Company workflow | Reuse source discovery, adapter selection, and validation |
| Lifecycle tracking | Extend the job store with update, missing, closed, and reopened events |
| Broader relevance ranking | Add skills, compensation, or company priority after deterministic filters |
| Assisted repair | Use saved diagnostics, fixtures, and adapter tests as evidence |

## First-release acceptance criteria

- [ ] A user can start one scan without configuring a scheduler or notification channel.
- [ ] The scan accounts for every enabled company or identifies the exact sources that failed.
- [ ] All supported adapters produce the normalized job contract.
- [ ] Every displayed job states the date basis used for the ten-day decision.
- [ ] Only configured roles and locations reach seniority evaluation.
- [ ] Repeated unchanged scans do not display the same job again.
- [ ] Repeated unchanged scans do not repeat LLM calls.
- [ ] The LLM seniority decision is schema-validated and includes description evidence.
- [ ] A broken source cannot silently appear as a healthy empty board.
- [ ] One failed source does not prevent healthy sources from returning results.
- [ ] The report distinguishes no matches from incomplete coverage.
- [ ] Tests and Git history make meaningful changes reviewable and reversible.

## Recorded design decisions

| Decision | Reason |
|---|---|
| Manual trigger first | It proves collection, filtering, state, and reporting without unattended execution complexity |
| Rolling ten-day window | It limits the candidate set and keeps reports focused on recent opportunities |
| Role and location before the LLM | These filters are inexpensive, consistent, and explainable |
| LLM for seniority | Seniority requirements often appear in description text instead of structured fields |
| LLM for onboarding, not routine fetching | Saved adapters are faster, cheaper, and easier to test |
| Basic persistent duplicate store | A recent posting should not reappear on every trigger |
| Adapter families instead of company scrapers | Most companies share a small number of ATS platforms |
| Human approval for repairs | An incorrect automatic source rewrite could silently hide jobs |
| Source errors remain visible | An incomplete scan must not look like a successful scan with no matches |

## Related documents

- [Implementation Guide](02_Job_Posting_Discovery_Implementation_Guide.md)
- [Phased Execution Plan](03_Job_Posting_Discovery_Phased_Execution_Plan.md)
