# Approved Product Decisions

**Status:** Approved first-release baseline

**Decision date:** 2026-09-20

**Applies to:** The first manually triggered version of the job-posting discovery system

This document records the product choices already made by the user. An implementation agent should treat them as requirements, not reopen them unless real source evidence exposes a material conflict.

## Company scope

The first release must include every company in the canonical seed: all 330 companies in [`data/company_seed.csv`](../data/company_seed.csv).

The `priority` field may control reporting order, implementation diagnostics, or triage order, but it must not exclude a company from the first release. A company that cannot be supported must remain visible with an explicit status and reason.

## Target roles

The search primarily targets AI and machine-learning roles, including:

- Machine learning and applied AI engineering.
- Large language models and generative AI.
- Fine-tuning, post-training, evaluation, and model adaptation.
- Retrieval-augmented generation, retrieval, embeddings, and search systems.
- Quantization, inference optimization, and model-serving optimization.
- AI agents, tool use, agent orchestration, and related platforms.
- Model Context Protocol (MCP) and closely related agent-integration work.
- Closely related AI/ML research, platform, infrastructure, and product-engineering roles when the job itself substantially involves these areas.

This is the approved intent, not the final keyword list. Phase 1 must derive and test title synonyms, exclusions, and difficult examples. Human checkpoint H1 is for reviewing that derived vocabulary and its examples, not for asking the user to restate the high-level scope.

## Location and work mode

- Accept roles anywhere in India.
- On-site, hybrid, and remote work modes are all acceptable.
- A remote role passes the location rule only when India is an allowed work location or the posting otherwise clearly accepts applicants based in India.
- Global or ambiguous remote roles require an explicit, evidence-based location decision; they must not silently pass as India roles.

## Experience and seniority

Include jobs that are open to candidates with fewer than five years of experience.

Seniority is decided by the LLM from the job description and requirements, after the
deterministic filters. Since `to_change.md` 2.5 that judgment is part of **one merged
call** that also decides AI/ML relevance and, when the deterministic filter could not
resolve it, India eligibility. The deterministic order is **location first, then title**.

Boundary rules:

| Posting requirement | Expected decision |
|---|---|
| `2+ years` | Include |
| `4+ years` | Include |
| `5+ years` | Exclude |
| `3–5 years` | Include, because candidates with fewer than five years are eligible |
| `5–7 years` | Exclude |
| No explicit years, but clearly early-career scope | Include |
| No explicit years and genuinely ambiguous scope | Keep visible as uncertain for review |

A title such as `Senior Machine Learning Engineer` must not be deterministically rejected before the LLM reads the description. The actual minimum experience and scope control the decision.

The seniority path has a labelled evaluation set and a 90% agreement gate (`job-finder validate-seniority`). The relevance judgment does **not** — its 20-case set exists but is never run against a model. See `docs/decisions.md`, open questions.

### Seniority quality threshold and uncertainty policy

Human checkpoint H9 was approved on 2026-09-23. The first-release seniority quality gate requires:

- At least 90% exact agreement on the reviewed `seniority_match` labels.
- 100% schema-valid results with locally verified verbatim evidence.
- Zero false acceptances and zero false rejections in the reviewed evaluation set.
- Every labelled ambiguous case to remain `uncertain`.

Detected-level agreement is diagnostic and does not control eligibility. An `uncertain` or invalid
result must appear in the dedicated manual-review section and must never be promoted to a match.
The system may re-evaluate such a result only after its description, search profile, seniority
prompt, or model policy changes. The approved prompt `1.0.1` baseline passed with 20/20 exact
eligibility decisions, valid verbatim evidence for all 20 results, and no false acceptance, false
rejection, or ambiguity error. The supporting evidence is recorded in
`docs/reviews/h9_seniority_quality_review.md`.

## Role and location filtering approval

Human checkpoint H6 was approved on 2026-09-22 without row-labelled corrections. The complete
registry validation and stratified review sample therefore approve the deterministic role and
India-location behavior in search-profile version `1.1.0` as the Phase 6 baseline.

Generic engineering and data-science titles remain in the conditional-description lane rather
than being presented as final matches.

> **Updated 2026-09-30.** This phrasing survives but its scale inverted. `to_change.md`
> 2.2a widened the title filter, so `CONDITIONAL_DESCRIPTION` is now the outcome for
> *every* surviving title (~94% of retained rows) rather than a narrow exception, and
> `EXPLICIT_PASS` is unreachable. Nothing bypasses the LLM gate. See `docs/decisions.md`
> D1. Missing or unresolved locations remain visible for review,
and roles explicitly restricted to non-India locations remain excluded. The approved review
evidence is recorded in `docs/reviews/h6_filter_review.md`.

## Publication-date uncertainty

The H5 review approved the documented hybrid policy on 2026-09-22. Strict ten-day results use
only verified publication timestamps. Updated values, date-only boundary overlaps, and unverified
or missing source dates remain visible in a separate uncertain-date section. Jobvite and
SuccessFactors may retrieve verified detail dates only after deterministic title and India-location
filters. Workday, Lever, Darwinbox, and Eightfold retain uncertain evidence and use persisted
`first_seen` only for forward-only aging after the initial baseline; it is never relabelled as a
publication time.

Under this approved policy:

- Preserve the source's raw date text and the normalized date basis.
- Keep postings with unreliable, missing, or ambiguous dates in a separate uncertain-date section.
- Do not silently classify those postings as either inside or outside the rolling ten-day window.
- Do not silently substitute an updated date for a publication date.
- Record a trustworthy `first_seen` timestamp for forward-only aging in future runs.

### Required Phase 5 report

After listing and date normalization has run across the entire enabled registry, the agent must report:

- Total enabled companies.
- Companies for which every observed listing has a reliable publication date.
- Companies with a mixture of reliable and uncertain dates.
- Companies whose observed listings have no reliable publication dates.
- Companies with no listings or that could not be assessed, shown separately.
- Total observed listings with reliable, uncertain, invalid, and missing dates.
- Percentages by company and by listing.
- The same breakdown by adapter or source family.
- Whether `first_seen` is available and meaningful for subsequent runs.
- Representative company names, job URLs, raw date labels, and interpretations for each uncertainty pattern.

Human checkpoint H5 was mandatory after this report. The user selected option 4 based on the
measured impact. The historical choices were:

1. Exclude uncertain-date jobs from strict ten-day results.
2. Include them in a clearly separate uncertain-date section.
3. Use `first_seen` for forward-only recency after the initial baseline.
4. Apply a documented hybrid policy by adapter or evidence type.

(H5 was approved 2026-09-22; the date policy below is settled.)


## Related documents

- [System Design](archive/01_job_posting_discovery_system_design.md)
- [Implementation Guide](archive/02_job_posting_discovery_implementation_guide.md)
- [Phased Execution Plan](archive/03_job_posting_discovery_phased_execution_plan.md)
