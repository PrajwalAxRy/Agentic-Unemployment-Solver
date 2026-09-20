# H1 search-policy review

**Checkpoint:** H1

**Status:** Awaiting user approval

**Prepared:** 2026-09-20

**Applies to:** Proposed first-release search profile `india-ai-ml-under-five-years`

**Important:** This is a review proposal, not active configuration. Source discovery must not begin
until this checkpoint is approved.

## Already-approved product baseline

The proposal below refines, and does not reopen, these decisions from `docs/04_product_decisions.md`:

- All 330 canonical companies remain in scope.
- The listing window is a rolling ten days.
- Role and India location are deterministic filters applied before description retrieval and LLM
  evaluation.
- On-site, hybrid, and remote work are acceptable when India eligibility is explicit.
- The LLM decides whether a job is open to candidates with fewer than five years of experience.
- Uncertain publication dates remain under `measure_then_decide` until mandatory checkpoint H5.

## Recommended title-matching model

Normalize case, Unicode punctuation, slashes, and common hyphenation, then match whole words or
phrases. Use two deterministic title lanes: explicit target titles pass directly, while approved
generic engineering and data-science titles become conditional candidates whose descriptions must
confirm substantive AI/ML work. Seniority words such as `senior`, `lead`, `staff`, `principal`,
`manager`, and `director` do not cause a deterministic rejection; the LLM will read the description
and experience requirements later.

### Proposed role families and accepted title terms

| Family ID | Intent | Accepted title terms and variants |
|---|---|---|
| `ml_engineering` | Build and productionize ML systems | `machine learning engineer`, `ML engineer`, `applied ML engineer`, `deep learning engineer`, `computer vision engineer`, `NLP engineer`, `speech ML engineer` |
| `generative_ai_engineering` | Build LLM and generative-AI products | `AI engineer`, `applied AI engineer`, `generative AI engineer`, `GenAI engineer`, `LLM engineer`, `foundation model engineer`, `conversational AI engineer` |
| `research_and_applied_science` | Model research or applied-science work | `machine learning scientist`, `AI research engineer`, `ML research engineer`, `research scientist` with an AI/ML/LLM qualifier, `applied scientist` with an AI/ML/LLM qualifier, `data scientist` with an AI/ML/LLM/deep-learning qualifier; unqualified scientist titles use the conditional lane below |
| `retrieval_search_and_rag` | Search, relevance, retrieval, embeddings, and RAG | `search engineer`, `enterprise search engineer`, `relevance engineer`, `retrieval engineer`, `RAG engineer`, `vector search engineer`, `embedding engineer` |
| `model_systems_and_optimization` | Training/inference performance and deployment | `ML systems engineer`, `AI systems engineer`, `inference engineer`, `model serving engineer`, `model optimization engineer`, `quantization engineer`, `AI compiler engineer`, `ML compiler engineer` |
| `ml_platform_and_infrastructure` | Platforms and infrastructure for model delivery | `MLOps engineer`, `ML platform engineer`, `AI platform engineer`, `LLM platform engineer`, `ML infrastructure engineer`, `AI infrastructure engineer` |
| `agents_and_tooling` | Agents, orchestration, tools, and MCP | `AI agent engineer`, `agentic AI engineer`, `agent platform engineer`, `LLM agent engineer`, `AI orchestration engineer`, `Model Context Protocol engineer`, `MCP engineer` only when the title also contains AI, LLM, agent, or Model Context Protocol context |
| `ai_software_and_product_engineering` | Software roles whose title explicitly identifies target AI work | `software engineer` or `backend engineer` with an AI/ML/LLM/GenAI/RAG/agent/search qualifier, `forward deployed engineer` with an AI/ML qualifier, `AI solutions engineer`, `AI architect`, `ML architect`; unqualified software titles use the conditional lane below |

### Conditional generic-title lane

The pre-description role gate has three outcomes:

1. `explicit_role_pass`: the title contains a target role and topic.
2. `conditional_description_check`: the title is a plausible generic engineering or science role.
3. `role_reject`: neither lane applies, or an explicit exclusion takes precedence.

Proposed conditional titles are:

- `software engineer`, `software development engineer`, and the structured abbreviation `SDE`.
- `backend engineer` and `backend software engineer`.
- `data scientist`, `applied scientist`, and `research scientist`.

Conditional candidates are still selected deterministically before description retrieval. Only
recent, India-eligible candidates in this bounded title set receive a description fetch. The fetched
description then passes a second deterministic AI-work check before any seniority LLM request.

The AI-work check passes when responsibilities or required qualifications show substantive work in
at least one of these areas:

- Building, training, fine-tuning, adapting, or evaluating ML, deep-learning, or foundation models.
- Building LLM, generative-AI, NLP, speech, computer-vision, RAG, retrieval, embedding, or agent
  systems.
- Deploying, serving, optimizing, quantizing, or operating models or ML inference infrastructure.
- Engineering AI product capabilities through model APIs, vector databases, agent tools, model
  evaluation frameworks, or production ML pipelines.

Incidental text does not pass: company boilerplate saying the product is AI-powered, use of coding
assistants, collaboration with a separate AI team, or generic requests for an "interest in AI" are
insufficient. The filter must return the matching description evidence and a machine-readable
reason. Phase 6 will measure the conditional-lane volume, description-fetch count, pass rate, and
review samples separately.

### Proposed abbreviations and spelling equivalence

- `AI/ML`, `AI - ML`, and `AI ML` are equivalent to explicit AI and machine-learning qualifiers.
- `ML` means machine learning only as a distinct title token, not as letters embedded in a word.
- `Gen AI`, `GenAI`, and `generative AI` are equivalent.
- `LLM` and `large language model` are equivalent.
- `MLOps`, `ML Ops`, and `machine learning operations` are equivalent.
- `RAG` counts only as a distinct token; it is equivalent to `retrieval-augmented generation`.
- `NLP` is equivalent to `natural language processing`.
- `CV` is too ambiguous by itself; use it only with AI/ML or explicit `computer vision` context.
- `MCP` is too ambiguous by itself; require AI/LLM/agent context or the full phrase `Model Context
  Protocol`.

### Proposed deterministic title exclusions

These phrases take precedence over a broad AI/ML term because the title identifies a different job
function:

| Exclusion phrase | Reason |
|---|---|
| `AI sales engineer`, `ML sales engineer`, `sales engineer` | Commercial sales function |
| `presales engineer`, `pre-sales engineer`, `sales consultant` | Commercial presales function |
| `solution consultant`, `solutions consultant` | Consulting title without an engineering signal; `AI solutions engineer` is intentionally not excluded |
| `account executive`, `account manager`, `business development` | Commercial account or growth function |
| `customer success manager`, `customer success specialist` | Customer-success function rather than target engineering |
| `product manager`, `program manager`, `project manager` | Management of product/program/project rather than implementation |
| `AI trainer`, `model trainer`, `AI training specialist`, `AI training quality specialist` | Human data or training-operations work rather than model engineering |
| `data annotator`, `data labeler`, `data annotation`, `data labeling` | Data operations rather than target engineering |
| `AI evaluator`, `model evaluator` | Human evaluation role; do not confuse with engineering roles that build evaluation systems |
| `prompt writer`, `AI content writer`, `AI content reviewer` | Content-production function |
| `AI recruiter`, `AI marketing`, `AI policy`, `AI governance` | Recruiting, marketing, policy, or governance function |

`Senior`, `staff`, `principal`, `lead`, `manager`, and `director` are not exclusions when the title
otherwise belongs to a target family. This follows the approved requirement that title seniority
must not preempt the description-based LLM decision.

### Deliberate title edge cases

| Title | Proposed result | Reason |
|---|---|---|
| `Senior Machine Learning Engineer` | Role pass | Target family; seniority is deferred to the LLM. |
| `AI Solutions Engineer` | Role pass | Explicit AI engineering title; do not blanket-exclude customer-facing technical work. |
| `AI Sales Engineer` | Role reject | Exact commercial exclusion takes precedence. |
| `Staff Data Scientist – Graph Neural Networks & Predictive AI` | Role pass | Explicit ML technique and AI qualifier. |
| `Data Scientist` | Conditional description check | Include only when responsibilities or requirements confirm substantive AI/ML work. |
| `Senior Software Engineer` | Conditional description check | Generic title is retained; the description must confirm substantive AI/ML product or systems work. |
| `Senior Software Engineer, AI Agents` | Role pass | Generic engineering title has an explicit target qualifier. |
| `Backend Engineer - Search` | Role pass | Explicit search-system qualifier. |
| `Lead Product Manager – Agentic Experiences` | Role reject | Product-manager exclusion takes precedence. |
| `Engineering Manager, Machine Learning Platform` | Role pass | Target family; the LLM evaluates the actual minimum experience. |
| `AI/ML Evaluator - English` | Role reject | Human evaluation role, not evaluation-systems engineering. |
| `MCP Engineer` | Role uncertain/reject by default | MCP is ambiguous without Model Context Protocol or AI/agent context. |
| `Computer Vision Engineer` | Role pass | Established ML subfield. |
| `CV Engineer` | Role uncertain/reject by default | `CV` alone is ambiguous. |

## Public title sample used to challenge the vocabulary

These pages were read only to test the proposed vocabulary. They are not Phase 2 source approvals.

| Company from seed | Public title and location observed | Proposed decision | Evidence |
|---|---|---|---|
| Atomicwork | `AI Engineer - Enterprise Search`, Bengaluru, India | Role pass; location pass | [Official public job page](https://job-boards.greenhouse.io/atomicwork/jobs/4495248008) |
| Atomicwork | `Backend Engineer - Search`, Bengaluru, Karnataka | Role pass; location pass | [Official public board](https://job-boards.greenhouse.io/atomicwork) |
| Atomicwork | `Solution Consultant`, Bengaluru | Role reject | [Official public board](https://job-boards.greenhouse.io/atomicwork) |
| Aera Technology | `AI/ Machine Learning Engineer`, Pune, India, hybrid | Role pass; location pass | [Official public job page](https://jobs.lever.co/aeratechnology/05e71552-a936-4067-976e-fbad0a3698e0) |
| Neuron7.ai | `AI Solutions Engineer`, Bengaluru, hybrid | Role pass; location pass | [Official public job page](https://jobs.lever.co/neuron7/706de3f1-579d-442e-b34a-b9d8a459d40c) |
| Neuron7.ai | `Senior Forward Deployment Engineer (FDE) (AI/ML \| Python) \| 6+ Years`, Bengaluru | Role pass; location pass; likely seniority exclude after description review | [Official public board](https://jobs.lever.co/neuron7?location=Bengaluru) |
| Neuron7.ai | `Technical Customer Success Manager– Enterprise AI & SaaS Platform \| 8+ Years`, Bengaluru | Role reject | [Official public board](https://jobs.lever.co/neuron7?location=Bengaluru) |
| Neuron7.ai | `Lead Software Engineer – AI Platform Engineering`, Bengaluru | Role pass; seniority deferred | [Official public board](https://jobs.lever.co/neuron7?location=Bengaluru) |
| Neuron7.ai | `Staff Data Scientist – Graph Neural Networks (GNN) & Predictive AI`, Bengaluru | Role pass; seniority deferred | [Official public board](https://jobs.lever.co/neuron7?location=Bengaluru) |
| Neuron7.ai | `Lead Product Manager – Agentic Experiences`, Bengaluru | Role reject | [Official public board](https://jobs.lever.co/neuron7?location=Bengaluru) |
| Nanonets | `Senior Software Engineer`, India; description includes engineering ML APIs, AI workflow features, and vector-database integrations | Conditional title, then AI-work pass; seniority remains deferred | [Official public job page](https://jobs.ashbyhq.com/nanonets/94ed41a9-3f11-4249-85f2-20a17c6f65f7) |

## Proposed India location policy

### Acceptance rules

1. Pass an on-site or hybrid posting when any listed work location is explicitly in India.
2. Pass a remote posting only when listing metadata or other pre-description source evidence explicitly
   says India is allowed.
3. Pass a multi-location posting when at least one listed location is explicitly allowed in India.
4. Do not require every location on a multi-location posting to be in India.
5. Keep missing, `Remote`, `Global`, `Worldwide`, and region-only locations such as `APAC` in a
   separate location-review state unless the source explicitly confirms India eligibility.
6. A location-review item does not pass to seniority evaluation and is not reported as a match.
7. Country code `IN` may be accepted only from a structured country field. Never match the free-text
   word `in` as India.

### Proposed aliases

Country-level values: `India`, `Republic of India`, structured ISO `IN`, and structured ISO3 `IND`.

Common city aliases:

| Canonical | Accepted aliases |
|---|---|
| Bengaluru | `Bengaluru`, `Bangalore` |
| Gurugram | `Gurugram`, `Gurgaon` |
| Delhi NCR | `Delhi`, `New Delhi`, `Delhi NCR`, `NCR` when used as a location field |
| Noida | `Noida`, `Greater Noida` |
| Mumbai | `Mumbai`, `Bombay` |
| Kolkata | `Kolkata`, `Calcutta` |
| Chennai | `Chennai`, `Madras` when used as a location field |
| Kochi | `Kochi`, `Cochin` |
| Thiruvananthapuram | `Thiruvananthapuram`, `Trivandrum` |
| Mysuru | `Mysuru`, `Mysore` |
| Mangaluru | `Mangaluru`, `Mangalore` |
| Visakhapatnam | `Visakhapatnam`, `Vizag` |

Also accept unambiguous India city or state/union-territory location values, including Hyderabad,
Pune, Ahmedabad, Gandhinagar, Coimbatore, Jaipur, Chandigarh, Mohali, Lucknow, Indore, Nagpur,
Bhubaneswar, Surat, Goa, and the official names of every Indian state and union territory. Phase 6
will store these in configuration rather than rely on this prose list.

### Location examples for approval

| Source location text | Proposed result | Reason |
|---|---|---|
| `Bengaluru, Karnataka, India` | Pass | Explicit India city and country. |
| `Bangalore` | Pass | Approved city alias. |
| `Pune, India (Hybrid)` | Pass | India location; hybrid is accepted. |
| `India` | Pass | Country-wide roles are accepted. |
| `Remote - India` | Pass | Remote eligibility explicitly includes India. |
| `Bangalore, India - Remote` | Pass | Remote role tied to an India location. |
| `Bengaluru; London; New York` | Pass | At least one explicit India location. |
| `Remote - India and Singapore` | Pass | India is explicitly allowed. |
| `Remote - APAC` | Location review, not pass | APAC alone does not prove India employment eligibility. |
| `Remote - Worldwide` | Location review, not pass | Global wording needs explicit evidence that India is eligible. |
| `Remote` | Location review, not pass | No allowed geography is stated. |
| `Asia` | Location review, not pass | Region-only and ambiguous. |
| `Singapore or Remote` | Reject/review, not pass | No explicit India location. |
| `San Francisco, CA` | Reject | Explicitly outside India. |
| missing location | Location review, not pass | Preserve uncertainty; do not silently include. |

## Publication-date policy and H5 measurement

Recommendation for H1: confirm only the measurement contract, not a final inclusion choice.

- Keep the profile value `measure_then_decide`.
- Verified first-publication timestamps alone receive inside/outside decisions.
- Updated, unverified, missing, invalid, and boundary-ambiguous date-only values stay in a separate
  measurement pool.
- At Phase 5, report all five company categories (`all_reliable`, `mixed`, `no_reliable`,
  `no_listings`, `unassessed`), all four listing states (`reliable`, `uncertain`, `invalid`,
  `missing`), percentages, adapter breakdowns, representative raw labels and URLs, and
  `first_seen_at` availability.
- Stop at H5 and choose among exclude, separate section, forward-only `first_seen`, or a documented
  hybrid. No default is proposed now.

The detailed technical contract is in `docs/05_recency_and_date_coverage_contract.md`.

## Proposed LLM seniority target

Question for the later evaluator:

> Based only on the job description and requirements, can a candidate with fewer than five years
> of total qualifying professional experience satisfy at least one stated eligibility path?

Rules:

- `2+` or `4+` required years pass; `5+` required years fail.
- An inclusive range such as `3–5 years` passes because candidates below five are eligible.
- Optional or preferred experience does not override a lower required minimum.
- Alternative education/experience paths pass if any stated path permits fewer than five years.
- Do not infer exclusion from `senior`, `lead`, `staff`, or `principal` in the title alone.
- When requirements conflict or the scope is genuinely ambiguous, return `uncertain` for review.
- Ignore irrelevant numbers such as product age, team size, or years since company founding.

### Labelled seniority examples

| # | Description evidence | Expected | Rationale |
|---:|---|---|---|
| 1 | `1–2 years of relevant ML experience` | Include | Every eligible value is below five. |
| 2 | `2+ years of software engineering experience` | Include | Minimum is below five. |
| 3 | `4+ years building production ML systems` | Include | A four-year candidate is eligible. |
| 4 | `5+ years of relevant experience required` | Exclude | Minimum is five. |
| 5 | `3–5 years of experience` | Include | The range explicitly permits three or four years. |
| 6 | `5–7 years of experience` | Exclude | No value below five is eligible. |
| 7 | `At least 7 years total, including 3 years in ML` | Exclude | Total required experience is at least seven. |
| 8 | `2 years required; 5 years preferred` | Include | Preferred experience does not change the lower required minimum. |
| 9 | `4 years required; 6+ years strongly preferred` | Include | A four-year candidate still satisfies the requirement. |
| 10 | `Bachelor's plus 3 years, or Master's plus 1 year` | Include | Both alternative paths permit fewer than five years. |
| 11 | `5+ years, or a PhD with no industry experience requirement` | Include | At least one explicit alternative path permits fewer than five years. |
| 12 | `New graduates and candidates with internship experience are welcome` | Include | Clearly early-career scope with no five-year minimum. |
| 13 | Title is `Senior ML Engineer`; description requires `3+ years` | Include | Description minimum controls; title alone does not exclude. |
| 14 | Title is `Junior AI Engineer`; description requires `6+ years` | Exclude | Description minimum controls; junior title does not include. |
| 15 | `3+ years` in one required section and `8+ years` in another | Uncertain | Conflicting minimum requirements need review. |
| 16 | No years; owns one service with mentoring available and bounded scope | Include | Description is clearly compatible with early-career execution. |
| 17 | No years; sets org-wide architecture, manages multiple teams, and owns strategy | Uncertain | Strong senior signals exist, but no explicit eligibility boundary proves exclusion. |
| 18 | No years and only generic responsibilities such as `build scalable AI systems` | Uncertain | Insufficient seniority evidence. |
| 19 | `Our company has 10 years of ML experience` and no candidate requirement | Uncertain | The number is irrelevant to candidate eligibility. |
| 20 | `Up to 5 years of experience` | Include | The stated range permits candidates below five. |

## Assumptions and recommendations requiring H1 approval

1. **Generic titles:** Treat approved software-engineering and science titles as conditional rather
   than rejecting them. Fetch descriptions only after recency and India-location checks, require
   deterministic evidence of substantive AI/ML work, and call the LLM only for seniority after that
   evidence passes. Recommendation: approve; this addresses the user-identified coverage gap and
   the Nanonets example while keeping role relevance deterministic.
2. **AI solutions engineering:** Include `AI Solutions Engineer` but exclude sales, presales,
   consultant, and customer-success titles. Recommendation: approve because the sampled Neuron7
   role writes production code, agents, parsers, and pipelines.
3. **Ambiguous location:** Retain missing/global/APAC/remote-only values in a location-review pool,
   but do not pass them to the LLM or present them as matches. Recommendation: approve to preserve
   evidence without silently treating ambiguity as India eligibility.
4. **Multi-location:** Pass when any explicit location is in India. Recommendation: approve because
   the same requisition is available to an India-based applicant.
5. **Employment type:** Do not filter by full-time, contract, internship, or apprenticeship in the
   first release; role, location, recency, and seniority remain controlling. Recommendation: approve
   because no employment-type exclusion exists in the product baseline.
6. **Date uncertainty:** Acknowledge that H1 approves only `measure_then_decide` and the coverage
   fields. The final policy remains mandatory at H5.

## Approval requested

Approve this proposal as written, or return corrections by section. After approval, the decisions
will be encoded in the versioned search-profile configuration and labelled fixtures, the complete
330-company minimum-schema accounting check will run, and the approved baseline will be committed
before Phase 2 begins.
