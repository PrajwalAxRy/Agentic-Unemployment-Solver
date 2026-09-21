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

Include jobs that are open to candidates with fewer than five years of experience. Seniority is decided by the LLM from the job description and requirements, after deterministic role and location filtering.

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

A title such as `Senior Machine Learning Engineer` must not be deterministically rejected before the LLM reads the description. The actual minimum experience and scope control the decision. Phase 1 must add more labelled examples, and Phase 8 must validate them against real descriptions.

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

The agent must not choose a default, continue past H5, or hide affected companies while this decision is unresolved.

## Still to be reviewed at Phase 1

The approved baseline leaves a few implementation-level choices for H1:

- Exact title synonyms and role-family vocabulary.
- Explicit false-positive title exclusions.
- India-eligibility examples for global or ambiguous remote postings.
- At least ten seniority examples, including missing or conflicting experience requirements.

These reviews refine the approved scope; they do not change it unless the user explicitly says so.

## Related documents

- [System Design](01_job_posting_discovery_system_design.md)
- [Implementation Guide](02_job_posting_discovery_implementation_guide.md)
- [Phased Execution Plan](03_job_posting_discovery_phased_execution_plan.md)
