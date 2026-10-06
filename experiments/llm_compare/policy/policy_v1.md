# Job-screening policy v1.2 (approved 2026-10-06)

The single source of truth for what the job scanner shows. Every benchmark label and every
prompt (1.4.0 and v10) is written from this document; when it changes, labels and prompts
follow. Each rule notes where it came from: **[CB type]** = your casebook decision on that
job type (`casebook/decisions_v0.json`), **[Q n]** = your answer to requirement question n,
**[override]** = a job-level override you made on the review page, **[OQ n]** = your answer
to open question n in section 8, **[R ordinal]** = your answer on the 2026-10-06 label review
(`lab/label_review_2026-10-05.json`). Section 9 summarises what v1.2 changed.

---

## 1. Who the search is for and what gets shown

- **Candidate:** about three years of professional experience, based in India, looking for
  AI/ML work. [Q1]
- **Goal:** list every job that is AI/ML work *and* open to someone with fewer than five
  years of experience. Missing a relevant job is worse than showing an extra one.
- **Three judgments per job**, each made on its own evidence: relevance, seniority, and
  location (location only when the deterministic filter could not place the job).
- **What reaches the report:**

  | Relevance | Seniority | Result |
  |---|---|---|
  | show (core AI or AI-involved) | eligible | **match** |
  | show | uncertain | match, tagged "seniority uncertain" |
  | uncertain | eligible or uncertain | shown, tagged "relevance uncertain" |
  | hide | anything | hidden |
  | anything | not eligible | hidden |

  Inside "show", **core AI** jobs are listed before **AI-involved** ones. [Q9]

---

## 2. What counts as AI/ML

Building, training, fine-tuning, evaluating, serving or operating systems in any of these
areas [scope discussion]:
- generative AI and large language models, including agents, RAG, and prompt or context
  engineering inside a product;
- machine learning and deep learning;
- natural language processing;
- computer vision and image or video understanding, including OCR and perception;
- speech;
- recommendation, search and ranking;
- reinforcement learning;
- MLOps and ML infrastructure: training and inference platforms, model serving, GPU or
  accelerator clusters, feature stores, vector search;
- data science that builds predictive models;
- evaluation and benchmarking of AI systems.

---

## 3. How to read a posting

1. **Judge the work, not the vocabulary.** Most postings mention AI somewhere; the question
   is whether AI/ML is part of what *this person* builds, runs or is responsible for.
2. **Evidence weight, strongest first:** role-specific duties and REQUIRED qualifications →
   the hiring team's own stated work → the title → preferred qualifications. Company
   descriptions ("we are AI-first") count for nothing. [Q13]
3. **Team vs organisation.** A team whose stated work is building AI/ML systems counts as
   show, even when the listed duties are generic. A role that only *sits in* an AI
   organisation (a shared org paragraph, generic duties) is uncertain. A team *name* alone
   ("AI Platform team", no work described) is uncertain. [Google discussion, Q14]
4. **Build vs use.** Building AI systems counts whoever the users are, including agents
   and LLM tools for internal engineers. Using AI tools (coding assistants, AI code review,
   "AI fluency") never counts. [CB build_ai_internal, CB ai_tooling_only]
5. **Develop vs integrate.** Developing AI or perception algorithms is show; integrating
   someone else's algorithms into a product or platform is uncertain. [Q7]
6. **Templates.** Job-family template text (for example Barclays' standard
   "Accountabilities" block mentioning machine learning) is ignored; judge from the
   role-specific part. Exception: senior data-leadership roles (VP, head of data) under such
   a template are uncertain. [CB template_text, override 1675/1786]
7. **When torn** between showing and hiding, choose uncertain. But uncertain needs a
   concrete reason to think *this person* might do AI work; a stray AI mention unrelated
   to the duties is not enough. [benchmark finding on v9]

---

## 4. Relevance rules

### Show — core AI (AI/ML is the main work)
- ML, GenAI and LLM engineers; applied and research scientists, including PhD-only research
  roles [Q2c, Q3]; data scientists who build models [Q2d].
- Computer vision, NLP, speech, recommendation and search-ranking engineers [Q2g];
  developers of robotics or autonomous-driving perception algorithms [Q2h, Q7].
- MLOps, ML platform, model-serving, AI inference and GPU/accelerator infrastructure
  engineers [Q2f].
- Engineers who build AI agents or LLM systems, including for internal teams (an agent
  that diagnoses CI failures, an internal AI agent platform). [CB build_ai_internal]

### Show — AI-involved (AI/ML is an explicit, real part of the job)
- Duties include building, integrating or deploying ML models or AI features into the
  product, or finding AI opportunities and then building the prototype or implementation.
  [Q20]
- REQUIRED qualifications demand hands-on experience building with AI/ML (RAG, LLM
  applications, model training or deployment). [CB ai_skill_required, Q16]
- The hiring team's stated work is building AI/ML systems. [Google discussion]
- The title clearly names AI/ML work (AI Engineer, ML Engineer, Data Scientist, NLP,
  Computer Vision, Deep Learning, AI Platform, Inference, Gen AI, AI Advisor, AI Automation
  Engineer). The title alone is enough: show even when the description has no AI duties or
  there is no description. [Q15, Q22, R1607, R1770, R2272, R1024] The title must name AI
  *work*: an AI product name or an AI-flavoured job name does not override a more specific
  hide rule (AI product designers, annotation, sales of AI, AI-tool enablement).
  [decision 2026-10-06 on 53, 121, 453, 1035-1038, 1399]
- "Data Scientist" titles doing analytics, experimentation or forecasting. [CB ds_titles,
  Q2e]
- Google's standard requirement "experience integrating generative AI tools or LLM
  interfaces into workflows" on an engineering posting. [CB genai_template_req]
- Customer or solutions engineers who build or prototype with the AI for customers, or who
  deploy and configure the company's AI product for customers. [CB customer_ai, override
  1450, OQ1]
- Analysts with non-AI titles whose duties build machine-learning or predictive models
  (a "Staff Data Analyst" building churn models). If the duties are statistics only:
  uncertain. [OQ2]
- Chip design or verification for AI/ML accelerators or AI cluster interconnect.
  [CB ai_hardware, Q2i]
- AI evaluation or benchmarking, model risk and validation, or AI-operations leadership as
  the core job. [overrides 499, 1538, 1543]
- Testing, validating, supporting or securing AI systems as a real duty: QA of agentic and
  LLM apps, clinical validation of AI products, triage of perception algorithms, support
  engineers debugging model behaviour, security of AI agent sandboxes, security review of
  AI use cases. [R2214, R741, R3119, R72, R1204, R2229] The thing under test must be an
  AI system: using AI tools to test ordinary software is "using AI tools" (hide).
  [benchmark finding 2026-10-06]
- Writing prompts or LLM automations that are part of the deliverable (prompt and grounding
  work for an AI support product, LLM-based security automations). [R222, R749]
- Analysts whose duties build forecasting or decision models, or roles that require
  data-science/applied-AI experience. [R1415, R1674, R1693, R353]
- Data or compute platforms whose stated purpose includes ML training, evaluation,
  inference or model deployment, and infrastructure built for AI workloads (cluster
  capacity for ML, semantic search for agents). Core when that is the main work. [R2040,
  R962, R233, R203]
- AI consulting or delivery leadership that requires hands-on ML experience, and AI
  advisory leadership titles. [R1262, R1024]
- Quant, trading or risk roles whose duties name machine learning. [Q8]

### Uncertain (shown, tagged)
- The role only sits in an AI organisation, or only a team name mentions AI. [rule 3.3]
- A mostly traditional software role with a smaller AI requirement. [overrides 60, 3329]
- AI only as "knowledge of" or a preferred qualification that relates to what the role
  builds. If unrelated to the duties: hide. [Q17, Q18]
- Consultants, enterprise architects and practice leads who advise on or design AI
  solutions among other technologies. [CB consulting_ai, overrides 7, 345, 889]
- Product, program and strategy roles where AI is the main subject. [CB ai_product_strategy,
  Q2k]
- AI governance, AI quality and AI risk roles that only oversee, with no hands-on review,
  testing or securing of AI systems (those are AI-involved, above). [CB ai_governance_eval,
  narrowed by R2229]
- Integrating someone else's AI or perception algorithms. [Q7]
- Risk or econometric modelling without machine learning (counterparty-credit quant
  models, economists). [Q5, R1681 kept] Quant trading research on statistics alone, and
  credit-risk roles where ML is only "understanding", are hide. [R1337, R3379]
- Senior data leadership under a generic ML template. [rule 3.6]
- The posting says too little to tell **and** something in it points to AI/data work.
- Engineers who write code calling LLM APIs as one part of a non-AI product (for example an
  IDE extension that integrates "AI services"). [OQ4]
- Practice directors who own an AI business line but mostly lead client and pilot work.
  [OQ9]

### Hide (not AI)
- AI only in the company description or culture text. [Q13]
- Using AI tools at work: coding assistants, AI code review, AI fluency, prompting for
  productivity. [CB ai_tooling_only, Q19]
- Hedges with no commitment to build ("potentially leverage AI", "explore where AI could
  help"). [Q20]
- AI in a long list of skills or technologies unrelated to the duties. [override 1669]
- Job-family template text when the role-specific part is other work (not senior data
  leadership). [CB template_text]
- Data engineering, BI or data platforms whose output merely feeds data scientists. If
  the platform runs ML training, inference or model deployment, it is AI-involved or core
  (section above). [CB data_feeding_ml, Q2j, R2040]
- Data labelling and annotation roles. [CB annotation]
- Customer-facing, go-to-market, support or monitoring roles for an AI product where the
  person does not work with the AI technically. [CB customer_ai overrides 948, 1474, 2728,
  850]
- Consulting managers whose engagements merely include AI among many areas of a CRM or
  cloud practice. [override 941]
- An ordinary software role on an AI product team whose own work is not AI, such as the
  web frontend. [Q4]
- Classic image or signal processing with no learning or recognition component. [Q6]
- Configuring, testing, selling or securing a product in which AI is one feature among
  many. [carried over from 1.3.0]
- No description and a title that says nothing about AI or data. [benchmark finding on v9]
- Configuring a business platform vendor's AI features (Workday "AI-enabled features",
  Salesforce Data Cloud "AI-driven insights"). [OQ3]
- Product and UX designers of AI-powered experiences. [OQ5]
- Data-centre technicians and hardware operations, including for ML clusters. [OQ6]
- Trainers and enablement roles that teach AI tools or AI literacy. [OQ8]
- Non-engineering roles required to adopt or deploy AI tools in their function (a finance
  manager automating close with AI tools). [R531]
- Backend or full-stack engineers at an AI company whose own work is not AI, with ML only
  preferred. [R1010]
- Sales-operations or CRM system architects whose AI mention is the vendor's agent product
  among CRM duties. [R2933]
- Identity and authentication for AI agents (the work is IAM, not AI). [R491]

---

## 5. Seniority rules

A role is **eligible** when at least one stated REQUIRED path accepts fewer than five years
of professional experience. [Q1, Q23]

- **Eligible:**
  - required minimum below five years, including "4+" and ranges judged by their lower
    bound ("3-6", "4-6"); [Q1, Q24]
  - any alternative path below five years, including degree paths ("PhD + 0 years",
    "Master's + 2 years"), whatever the candidate's degree; [Q29]
  - internships, new-graduate, campus and early-career roles; [Q30]
  - no years stated and a junior title marker (Junior, Jr, Associate, Analyst, Graduate,
    Trainee, Apprentice, Engineer I/II, SDE 1/2), or duties framed as learning or working
    under guidance. [Q28]
- **Not eligible:**
  - every required path asks for five years or more ("5+", "8-12"); [Q25]
  - no years stated and a lead-level title: Lead, Staff, Principal, Manager, Head,
    Director, VP, AVP, Vice President. [Q27]
- **Uncertain:**
  - no years stated and the title is "Senior"/"Sr" without a lead-level word, or has no
    level marker, and the duties do not settle it; [Q26]
  - the requirements contradict each other.
- A stated number always beats the title ("Senior Engineer, 3+ years" is eligible).
- Preferred qualifications never override a lower required minimum.
- Numbers that are not experience requirements (company age, team size) are ignored.

---

## 6. Location rules (only for jobs the filter could not place)

- **India:** based in India or explicitly hires in India → shown.
- **Open remote:** remote with no restriction that excludes India, or open across APAC,
  worldwide or any time zone → shown, not uncertain. [Q33] This includes "Remote" with no
  region stated, wherever the company is headquartered. [OQ10]
- **Relocation:** based outside India but offers relocation or visa sponsorship → shown in
  a separate "Relocation" category. [Q34] *Limitation:* today the deterministic filter drops
  most non-India locations before the model sees them, so this mostly applies to remote
  postings until the filter is changed (planned with the production work).
- **Excluded:** restricted to another country or region without relocation, or requires a
  work authorisation, time zone or office that excludes India → hidden.
- **Uncertain:** the posting does not say → shown, tagged.

---

## 7. How benchmark labels are made

- Each job gets: relevance (core AI / AI-involved / uncertain / hide), seniority
  (eligible / uncertain / not eligible), location where applicable, a **confidence from 1 to
  10**, and a one-line reason.
- Confidence: **9–10** the policy decides it plainly; **7–8** clear, but a reader could
  pause; **5–6** a judgment call inside the policy; **1–4** the policy does not settle it,
  or two rules conflict.
- Labels are made **blind**: no model answer is seen while labelling.
- **You review** every job at confidence 4 or below, plus a random 50 of the rest to check
  that my confident labels can be trusted. If you change more than about 10% of those 50, I
  relabel more widely.
- Any answer you give that generalises becomes a new rule here (policy v1.1, v1.2, ...).
- **Scoring.** The primary score is **visibility** (shown = core, involved or uncertain,
  with seniority not "not eligible"; hidden otherwise), because that decides what you see.
  Core vs involved vs uncertain is a secondary, soft score: on the 2026-10-06 review the
  same job type landed on both sides of the uncertain/involved line (Salesforce architects
  897 involved; 834, 892, 900 uncertain), so no prompt can be held to that line exactly.

---

## 8. Open questions — resolved 2026-10-05

Your answers: 5 → **hide** (not uncertain as proposed), 10 → **show** as open remote (not
uncertain as proposed); the other eight as proposed. Each is now a rule in sections 4 and 6,
tagged [OQ n]. The original wording, with my proposals in brackets:

1. Customer-facing engineers who **deploy and configure** the company's AI product for
   customers, without building models (for example a customer-success technical manager
   who sets up an AI field-service product). [show: they work with the AI technically]
2. **Analysts with non-AI titles** whose duties build predictive or ML models (a "Staff Data
   Analyst" building churn models, a business analyst using predictive modelling for
   collections). [show if machine learning or predictive models are in the duties;
   uncertain if only statistics]
3. Engineers on **business platforms** whose duties mention enabling the vendor's AI
   features: Workday HR with "AI-enabled features", Salesforce Data Cloud "AI-driven
   insights". [hide: configuring a vendor's AI feature is product configuration]
4. Engineers who **write code that calls LLM APIs** as one part of a non-AI product (for
   example an IDE extension that integrates "AI services"). [uncertain]
5. **Product or UX designers** of AI-powered experiences. [uncertain, like AI product
   managers]
6. **Data-centre technicians and hardware operations** for ML clusters. [hide]
7. **Security engineers** whose duties include red-teaming or securing AI systems alongside
   other security work. [uncertain, under AI security]
8. **Trainers and enablement roles** that teach AI tools or AI literacy. [hide]
9. Practice directors who **own an AI business line** and lead its client delivery (for
   example "build next-gen credit AI solutions", mostly client and pilot work).
   [uncertain]
10. **"Remote" with no region stated**, at a company headquartered outside India.
    [uncertain]

---

## 9. Changes in v1.2 (label review, 2026-10-06)

You reviewed 103 labels: all 53 at confidence 5 or lower and a random 50 of the rest.
- **Confident labels hold:** 1 of 50 changed (2%, under the 10% relabel threshold).
- **Low-confidence labels:** 32 of 53 changed, 25 of them uncertain → AI-involved/core
  (still shown, only the tag moves), 6 to hide and 1 hide → show. The new and narrowed
  rules above carry an [R ordinal] tag.
- **Net direction:** most "uncertain" cases that involve hands-on work *with* AI systems
  (testing, securing, integrating, platform for ML, forecasting models) are now
  AI-involved; cases where AI is only a tool, a preference or a vendor CRM feature are hide.

