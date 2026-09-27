# Phase 11 Atomicwork custom-adapter activation review

## Checkpoint status

**STOP — Human checkpoint H11. The adapter is implemented and validated; active configuration is
unchanged.**

- Proposal ID: `repair-067463ff973ca40d`
- Proposal status: `implemented; inactive pending approval`
- Affected company: Atomicwork only (`company_id=atomicwork`)
- Change type: custom-adapter activation
- Confidence: high
- Implementation commit: `fc9734c` (`feat: add Atomicwork Webflow adapter`)
- H4 decision: `build Atomicwork custom adapter`, approved 2026-09-28

## Observed failure and bounded repair

Atomicwork was the only failed enabled source in the 2026-09-27 pilot attempt. Its retired
Greenhouse API returns HTTP 404, while the official public careers page and sitemap expose six
matching Webflow detail pages. The implementation is deliberately company-specific:

- it accepts only `https://www.atomicwork.com/company/careers` and same-origin
  `/careers/<id-or-slug>` detail URLs;
- it reconciles the complete visible Webflow collection with the public sitemap;
- it derives stable external IDs from detail paths and preserves those detail pages as canonical;
- it leaves every publication date `unknown`;
- it retrieves descriptions only through the existing post-filter detail path; and
- it fails visibly on missing schema markers, unexplained empty inventory, malformed rows,
  duplicate IDs, off-origin links, redirects, or listing/sitemap disagreement.

The old Greenhouse Apply targets embedded in some current detail pages are retained only as
diagnostic metadata. The adapter does not follow them or present them as canonical job URLs.

## Exact proposed active-registry diff

Approval authorizes only the following Atomicwork record change plus its registry regression
assertions. It does not authorize changes to another company, the search profile, or job-history
state.

```diff
-      "careers_url": "https://job-boards.greenhouse.io/atomicwork",
-      "adapter_type": "greenhouse",
+      "careers_url": "https://www.atomicwork.com/company/careers",
+      "adapter_type": "custom",
       "adapter_parameters": {
-        "board_token": "atomicwork"
+        "adapter_key": "atomicwork_webflow"
       },
       "identity_strategy": "external_id",
       "date_strategy": {
-        "field_name": "first_published",
-        "basis": "published",
-        "verified_as_publication": true,
-        "notes": "Imported from a provisional Phase 2 discovery proposal."
+        "field_name": null,
+        "basis": "unknown",
+        "verified_as_publication": false,
+        "notes": "Official Webflow listing and detail pages expose no trustworthy publication date."
       },
-      "detail_strategy": "listing_payload",
+      "detail_strategy": "detail_page",
       "enabled": true,
       "confidence": "high",
       "evidence": [
-        "https://job-boards.greenhouse.io/atomicwork",
-        "https://boards-api.greenhouse.io/v1/boards/atomicwork/jobs",
-        "https://docs.greenhouse.io/job-board.html",
-        "https://boards-api.greenhouse.io/v1/boards/atomicwork/jobs?content=true"
+        "https://www.atomicwork.com/company/careers",
+        "https://www.atomicwork.com/sitemap.xml",
+        "https://www.atomicwork.com/careers/4062696008",
+        "https://www.atomicwork.com/careers/4417546008-5ddb5"
       ],
       "low_confidence_approved": false,
       "exception_reason": null,
-      "notes": "Greenhouse public Job Board API passed full adapter-group validation; jobs without first_published retain updated_at separately for H5.",
+      "notes": "H4-approved bounded Atomicwork Webflow adapter; listing and sitemap inventories must agree; publication dates remain unknown; legacy Greenhouse Apply targets are not canonical.",
       "source_rank": 33,
       "priority": "P1",
-      "last_verified_at": "2026-09-20T12:40:52+05:30"
+      "last_verified_at": "2026-09-28T00:38:13+05:30"
```

Expected registry accounting after activation remains 330 canonical companies and 86 enabled
sources. The adapter distribution changes from 25 Greenhouse / 0 custom to 24 Greenhouse / 1
custom.

## Fixture and automated evidence

Eight focused adapter tests pass. Sanitized fixtures cover:

- a healthy listing reconciled with its sitemap;
- an explicit empty Webflow collection and empty sitemap;
- a malformed row;
- duplicate path-derived IDs;
- an off-origin detail link;
- listing/sitemap disagreement; and
- full detail extraction with title, location, description, and retained application metadata.

The complete repository validation passes at commit `fc9734c`:

- Ruff format: pass;
- Ruff lint: pass;
- strict mypy: pass across 90 source files; and
- pytest: 474 passed.

After adding this checkpoint artifact and its contract test, the current complete validation also
passes with 475 tests.

## Inactive live evidence

The exact proposed Atomicwork source was overlaid in memory; `config/company_sources.json` was not
changed. The normal verifier and truthful bounded HTTP client produced:

- outcome `success`, completeness `true`, one attempt;
- six unique jobs across the careers page and sitemap;
- zero missing required fields;
- six `unknown` date-basis values and the expected `missing_publication_date` warning; and
- matching listing and sitemap URL sets.

Two official details were then fetched through the adapter:

- `4417546008-5ddb5`, Product Marketer, Palo Alto, California, 3,609 description characters;
- `4062696008`, Backend Engineer, Bengaluru, India, 5,842 description characters.

Both details preserved their path identity and unknown date basis. The ignored sanitized verifier
output is `reports/phase11_atomicwork_custom_inactive.json`.

## State and rollback

The schema-3 job-history database currently contains 394 records: 22 pending, 195 completed, and
177 failed. A read-only query again confirmed zero Atomicwork records, so activation requires no
identity migration and does not trigger H7.

If activation fails its post-change gates, revert only the Atomicwork registry record to the exact
Greenhouse values shown above. The custom adapter code can remain dormant without affecting other
sources. The activation commit will provide a single focused Git rollback point.

After approval, the required gates are:

1. registry regression and complete repository validation;
2. targeted Atomicwork custom-adapter verification;
3. complete remaining Greenhouse and custom-adapter group verification;
4. all-enabled source verification; and
5. a preserved-state full scan before the pilot can return to H12.

## Recommendation and required response

Approve activation. The adapter is narrow, public, fail-closed, fixture-covered, and live-verified;
leaving the retired Greenhouse mapping active guarantees another partial scan.

Reply with exactly one of:

- `approve repair-067463ff973ca40d`
- `reject repair-067463ff973ca40d: <reason>`
