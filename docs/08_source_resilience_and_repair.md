# Source resilience and repair runbook

## Purpose

Phase 10 keeps a broken or changed source visible without allowing it to erase healthy peer
results, corrupt job-history state, or modify active configuration automatically. Source
verification is read-only. Generated verification reports, repair requests, repair proposals, and
temporary live-test outputs are ignored local evidence.

Run commands from the repository root with the locked environment.

## Failure and anomaly model

Failures identify an understood failure mechanism:

| Category | Meaning |
|---|---|
| `temporary_availability` | A bounded request timed out or a retryable temporary response failed. |
| `rate_limit` | The public source returned a rate-limit response. |
| `configuration_error` | Required adapter configuration is missing or invalid. |
| `source_moved` | The configured public endpoint is no longer present, such as HTTP 404. |
| `schema_change` | A response type, required field, or recognized page structure changed. |
| `parser_defect` | The adapter found inconsistent pagination or another parser-level failure. |
| `access_restriction` | A login, CAPTCHA, or access-control page replaced public inventory. |
| `unsupported_source` | The source cannot be handled by the supported public adapter contract. |

Anomalies are suspicious observations, not inferred failure causes:

| Anomaly | Detection rule |
|---|---|
| `result_count_collapse` | A prior baseline had at least 20 jobs and the current complete result is at most 20% of it. |
| `future_publication_date` | A publication date is more than one day after verification time. |
| `stale_publication_dates` | At least five jobs all have publication dates more than 365 days old. |

An anomaly changes the verification outcome to `suspicious` and prevents the source from being
reported as healthy. It does not by itself assign a schema failure. For example, Quantbox
Research currently exposes eight public jobs whose old `first_published` values coexist with
recent `updated_at` values. That is retained as a reviewed stale-date anomaly rather than being
mislabeled as a schema change.

## Targeted verification

Verify one company:

```powershell
uv run --locked job-finder verify-sources `
  --adapter greenhouse `
  --company-id glean `
  --baseline reports/phase4_full_registry_verification.json `
  --source-retries 2 `
  --output reports/phase10_glean_verification.json
```

Omit `--company-id` to verify every configured source in an adapter family. Verify all enabled
sources with:

```powershell
uv run --locked job-finder verify-sources `
  --all-enabled `
  --baseline reports/phase4_full_registry_verification.json `
  --source-retries 2 `
  --output reports/phase10_full_registry_verification.json
```

The command emits one bounded progress line after each company. A nonzero exit status means at
least one source is failed or suspicious; healthy peer records and the sanitized report are still
preserved. Verification never opens or changes the job-history database.

Each report records company and adapter identity, configuration version, outcome, completeness,
job and page counts, date-basis distribution, sanitized diagnostic categories, stable failure and
anomaly categories, retry attempts, and up to three public sample URLs. It excludes descriptions,
response bodies, exception messages, cookies, credentials, and credential-like URL query values.

## Failure drills

The automated Phase 10 drills cover login and CAPTCHA pages, a removed required field, content-type
change, repeated pagination, timeout, rate limiting, historical count collapse, peer isolation,
future dates, unavailable LLM service, and state-lock contention. They assert bounded retries,
sanitized evidence, explicit nonhealthy outcomes, and continued healthy-peer processing.

Run the focused source drills with:

```powershell
uv run --locked pytest tests/test_failure_drills.py tests/core/test_access_detection.py `
  tests/test_verification.py tests/test_repair.py
```

Run the complete repository gate before committing a repair:

```powershell
uv run --locked python scripts/validate.py
```

## Guarded repair workflow

A repair request is deterministic, sanitized evidence for exactly one failed or suspicious
company. It gives a proposer evidence and constraints, never authority to edit the registry.

```powershell
uv run --locked job-finder repair build-request `
  --verification reports/phase10_full_registry_verification.json `
  --company-id sap `
  --output diagnostics/repair_requests/sap.json
```

Validate an inactive proposal against that request:

```powershell
uv run --locked job-finder repair validate-proposal `
  --request diagnostics/repair_requests/sap.json `
  --proposal diagnostics/repair_proposals/sap.raw.json `
  --output diagnostics/repair_proposals/sap.validated.json
```

The proposal must contain a stable matching proposal ID, exact before/after changes, confidence,
rationale, fixture and live-test plans, rollback instructions, and
`"activation_status": "inactive"`. Sensitive values and credential-like public URLs are rejected.

Test the exact proposal in memory without editing `config/company_sources.json`:

```powershell
uv run --locked job-finder repair test-proposal `
  --request diagnostics/repair_requests/sap.json `
  --proposal diagnostics/repair_proposals/sap.validated.json `
  --source-retries 2 `
  --output reports/phase10_sap_proposal_verification.json
```

Only the supported `careers_url` and `adapter_parameters` fields are overlaid in an immutable
in-memory registry. Stale `before` values, a mismatched registry version, duplicate paths, another
company, or any unsupported field fail closed.

## Activation and rollback

The repair system has no activation command. Before any tested proposal changes active registry,
adapter configuration, or source logic, stop at H11 and present the stable proposal ID, failure,
sanitized evidence, exact diff, confidence, affected companies, fixture and live results,
rollback, and recommendation.

After the user explicitly replies `approve <proposal-id>`, apply only the reviewed diff through a
normal focused code/configuration change, add regression evidence, rerun the affected adapter
group and all enabled sources, inspect the staged diff, and commit. On rejection, record the
disposition and leave active configuration untouched. Git retains the last working configuration;
rollback is the inverse of the reviewed diff followed by the same validations.
