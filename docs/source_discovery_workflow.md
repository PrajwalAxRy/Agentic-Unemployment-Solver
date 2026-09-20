# Source discovery workflow

## Purpose

Phase 2 source discovery proposes public company job sources for human review. A proposal is never
active runtime configuration: every imported source stays disabled until H2 approval and the later
adapter gates pass.

## LLM-assisted research prompt

For each canonical company, use only public evidence and return one structured proposal. Preserve
the supplied `company_id`, `company_name`, `source_rank`, and `priority` exactly. Research:

1. Official careers URL and any India or regional board.
2. ATS or source family and all required parameters: board token, tenant, site, locale, or slug.
3. Whether the source provides a complete list or only a search interface.
4. Public list endpoint and pagination behavior.
5. Job ID, publication-date, title, and location fields when observable.
6. Whether the date is a publication date, update date, first-seen value, or unknown.
7. Whether descriptions are in the listing payload, a detail endpoint, or a detail page.
8. Direct evidence URLs, confidence, and any login, CAPTCHA, terms, robots, rate-limit, or access
   concern.

Do not use recruiter or aggregator copies as the official source. Do not authenticate, solve a
CAPTCHA, evade a rate limit, or bypass access controls. If evidence is ambiguous, retain the
conflict explicitly rather than guessing.

## Output contract

The tracked version-1 discovery batch in `data/source_discovery_proposals.json` contains one record
for every canonical seed company. Its validated fields are defined by
`job_finder.core.source_discovery.SourceDiscoveryProposal` and include:

- stable seed identity and ordering;
- discovery status;
- official and regional URLs;
- adapter family, parameters, listing mode, endpoint, and pagination notes;
- external ID, publication date, title, and location field evidence;
- detail strategy;
- confidence, evidence records, access concern, and notes.

Ranked search evidence is explicitly labeled unreviewed. The guarded importer rejects weak scores,
known aggregator/social hosts, PDFs, and malformed URLs. Read-only verification stores only
sanitized status, redirect, content type, page title, and recognized job-count metadata under the
ignored `diagnostics/` directory. Full response bodies are never tracked.

For verified public pages, a second bounded pass detects unambiguous hosted ATS references. It can
classify Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Eightfold, iCIMS, Oracle Cloud,
SuccessFactors, Taleo, Jobvite, and Darwinbox parameters. Multiple detected boards remain
`search_only` for inspection instead of being collapsed into one configuration.

## Reproducible commands

```powershell
uv run --locked python scripts/build_source_discovery_baseline.py
uv run --locked python scripts/apply_search_discovery.py
uv run --locked python scripts/verify_discovery_proposals.py --timeout 8
uv run --locked python scripts/apply_source_verification.py
uv run --locked python scripts/apply_source_quality_corrections.py
uv run --locked python scripts/fingerprint_verified_sources.py --timeout 8
uv run --locked python scripts/apply_source_fingerprints.py
uv run --locked python scripts/build_company_registry.py
uv run --locked python scripts/audit_company_registry.py
uv run --locked python scripts/build_h2_source_review.py
uv run --locked python scripts/validate.py
```

Live commands may change external evidence and must be followed by full validation and review. The
canonical seed and provenance workbook are never rewritten by this workflow.
