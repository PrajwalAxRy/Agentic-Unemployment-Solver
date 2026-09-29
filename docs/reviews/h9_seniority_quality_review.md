# H9 seniority quality review

## Checkpoint status

**APPROVED — Human checkpoint H9 completed on 2026-09-23.**

Generated `2026-09-23T03:24:16+05:30` with model policy `amd-llm-gateway:gpt-5.6-luna:v1`, prompt `1.0.1`, evaluation set `1.0.0`, and search profile `1.1.0` (`b3da10cf2d1e6b762c1f6c3a24a71fcba93e6f80615fabe525103eb9f1a1569d`).

## Recommendation and result

Recommended first-release threshold: at least 90% exact agreement on the reviewed `seniority_match` labels; 100% schema-valid results with locally verified verbatim evidence; zero false acceptances; zero false rejections; and every labelled ambiguous case preserved as `uncertain`.

**The reviewed set passed the recommended threshold.**

Recommended uncertainty policy: keep `uncertain` and invalid results in a dedicated manual-review section and never promote either to a match. Re-evaluate only after the description, profile, prompt, or model policy changes.

## Aggregate quality

- Reviewed examples: 20; valid decisions: 20; invalid/manual-review outcomes: 0.
- Exact decision agreement: 20/20 (100.00%).
- Detected-level agreement: 15/20 (75.00%). Level is diagnostic; eligibility is the release decision.
- False acceptances: 0; false rejections: 0; ambiguity errors: 0.
- Limited live batch: 8 decisions; outcomes `{"false": 6, "true": 1, "uncertain": 1}`.

## Full-registry deterministic gate used for sampling

- Enabled companies: 86; source outcomes: `{"empty": 2, "success": 84}`; healthy: `true`.
- Retained role/location candidates: 333; explicit target roles eligible for this seniority sample: 115; conditional-description candidates deliberately not sent: 218.
- Live candidate limit: 8; usable selected candidates: 8; description collection issues before reaching the limit: 0.

Generic conditional-description titles were excluded from this Phase 8 quality batch. Their separate deterministic substantive-AI-work check must pass before seniority evaluation in the Phase 9 scan orchestration.

## Every reviewed-set disagreement

| Case | Title | Expected | Actual | Level expected/actual | Evidence | Status |
|---|---|---|---|---|---|---|
| — | — | — | — | — | None. | — |

## Every reviewed-set uncertain or invalid result

| Case | Title | Expected | Actual | Level expected/actual | Evidence | Status |
|---|---|---|---|---|---|---|
| seniority-15 | ML Software Engineer | uncertain | uncertain | unknown / mid | A later mandatory requirements section says candidates must have 8+ years of professional experience. | agree |
| seniority-17 | Principal AI Architect | uncertain | uncertain | principal / principal | Set organization-wide AI architecture, manage multiple engineering teams, and own long-range technical strategy. | agree |
| seniority-18 | AI Engineer | uncertain | uncertain | unknown / unknown | Build scalable AI systems and collaborate with product teams. | agree |
| seniority-19 | Machine Learning Engineer | uncertain | uncertain | unknown / unknown | no candidate experience requirement is provided. | agree |

## Complete reviewed evaluation set

| Case | Title | Expected | Actual | Level expected/actual | Evidence | Status |
|---|---|---|---|---|---|---|
| seniority-01 | Machine Learning Engineer | true | true | entry / junior | Candidates must have 1-2 years of relevant ML experience | agree |
| seniority-02 | Software Engineer, AI Platform | true | true | mid / mid | Requires 2+ years of software engineering experience and production Python knowledge. | agree |
| seniority-03 | ML Engineer | true | true | mid / mid | You need 4+ years building production ML systems. | agree |
| seniority-04 | Senior ML Engineer | false | false | senior / senior | Five or more years of relevant professional experience is required. | agree |
| seniority-05 | Applied AI Engineer | true | true | mid / mid | 3-5 years of experience in applied machine learning. | agree |
| seniority-06 | Senior AI Engineer | false | false | senior / senior | Applicants must bring 5-7 years of professional engineering experience. | agree |
| seniority-07 | Lead Machine Learning Engineer | false | false | lead / lead | At least 7 years total engineering experience is required, including 3 years in ML. | agree |
| seniority-08 | Machine Learning Engineer | true | true | mid / mid | Two years of relevant experience is required | agree |
| seniority-09 | AI Platform Engineer | true | true | mid / mid | Four years of engineering experience is required | agree |
| seniority-10 | Data Scientist | true | true | mid / mid | Eligibility is a bachelor's degree plus 3 years of experience, or a master's degree plus 1 year. | agree |
| seniority-11 | Research Scientist | true | true | unknown / unknown | or a PhD in a relevant field with no industry-experience minimum. | agree |
| seniority-12 | Graduate AI Engineer | true | true | entry / entry | New graduates and candidates with internship experience are welcome. | agree |
| seniority-13 | Senior Machine Learning Engineer | true | true | senior / senior | The role requires 3+ years of relevant professional experience. | agree |
| seniority-14 | Junior AI Engineer | false | false | junior / senior | Applicants must have 6+ years of professional software engineering experience. | agree |
| seniority-15 | ML Software Engineer | uncertain | uncertain | unknown / mid | A later mandatory requirements section says candidates must have 8+ years of professional experience. | agree |
| seniority-16 | Software Engineer, AI | true | true | entry / junior | Own one bounded AI service with design guidance and regular mentoring. | agree |
| seniority-17 | Principal AI Architect | uncertain | uncertain | principal / principal | Set organization-wide AI architecture, manage multiple engineering teams, and own long-range technical strategy. | agree |
| seniority-18 | AI Engineer | uncertain | uncertain | unknown / unknown | Build scalable AI systems and collaborate with product teams. | agree |
| seniority-19 | Machine Learning Engineer | uncertain | uncertain | unknown / unknown | no candidate experience requirement is provided. | agree |
| seniority-20 | Applied Scientist | true | true | mid / unknown | Applicants may have up to 5 years of relevant professional experience. | agree |

## Limited unseen live batch

| Case | Company | Adapter | Title and location | Date lane | Decision | Evidence | Link |
|---|---|---|---|---|---|---|---|
| live-01 | WisdomAI | ashby | Machine Learning Engineer — Bengaluru | strict_recent | uncertain | We are looking for exceptional ML/NLP engineers to join our team. | [job](https://jobs.ashbyhq.com/Wisdom-AI/35029bbd-c8cd-448a-8491-65ea639dbea2) |
| live-02 | Motive | greenhouse | AI Engineer — Bangalore, India | strict_recent | true | 4+ years of machine learning and/or data science experience | [job](https://job-boards.greenhouse.io/gomotive/jobs/8785037002) |
| live-03 | JPMorganChase | oracle_cloud | Senior Director of Software Engineering - Backend & AI — Hyderabad, Telangana, India \| 33435-JPMorgan Chase & Co Towers, H | strict_recent | false | Formal training or certification on software engineering concepts and 10+ years applied experience. | [job](https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210737125) |
| live-04 | SAP | successfactors | Principal AI Architect (Office of the CTO) — Bangalore, IN, 560066 | strict_recent | false | 15+ years of work experience in software architecture design and development. | [job](https://jobs.sap.com/job/Bangalore-Principal%C2%A0AI%C2%A0Architect%C2%A0%28Office-of-the-CTO%29-560066/1424596033/) |
| live-05 | Millennium Management | eightfold | AI Engineer — Bangalore, Karnataka, India | uncertain_date | false | 5–6 years of data engineering experience, including 1–2 years of hands-on AI experience | [job](https://mlp.eightfold.ai/careers/job/755957774129) |
| live-06 | Neuron7.ai | lever | Solution Architect – Salesforce Field Service & AI (GenAI / LLM) — Bengaluru | uncertain_date | false | 12+ years of experience in Solution Architecture / Enterprise Systems | [job](https://jobs.lever.co/neuron7/334c2ee0-2d8a-4c35-a65b-31b7f1c74fc4) |
| live-07 | Uniphore | workday | Principal Security Engineer, AI Security & SecOps — India - Bangalore | uncertain_date | false | 8 to 10+ years in a hands-on security engineering or operations role, with strong depth in security operations, incident response, and cloud security. | [job](https://uniphore.wd503.myworkdayjobs.com/Uniphore/job/India---Bangalore/Principal-Security-Engineer-V--Incident-Response---Operations_JR100694) |
| live-08 | EnCharge AI | greenhouse | AI Software Engineer, Agent Harness — India | strict_recent | false | 10+ years of software engineering experience in backend systems or ML infrastructure | [job](https://job-boards.greenhouse.io/enchargeai36/jobs/4409175009) |

## Agent evidence review

All eight live decisions were reviewed against the public description context captured by the
generated report and the linked job page:

- `live-02` is a correct match because its required minimum is four years.
- `live-03` through `live-08` are correct rejections because their required minimums are five years
  or higher (10+, 15+, 5–6, 12+, 8–10+, and 10+ years respectively).
- `live-01` is an appropriate uncertainty: the WisdomAI description has demanding scope and
  ownership language but no numeric minimum or explicit early-career eligibility path.
- Every decision contains a locally verified contiguous excerpt from its description. No schema
  failure, unsupported acceptance, unsupported rejection, or systematic prompt defect remains in
  this batch.

The full-registry sampling pass completed at `2026-09-23T03:08:53+05:30`; the prompt-1.0.1 exact
candidate refresh completed at the report generation time above.

## Every live uncertain or invalid result

| Case | Company | Adapter | Title and location | Date lane | Decision | Evidence | Link |
|---|---|---|---|---|---|---|---|
| live-01 | WisdomAI | ashby | Machine Learning Engineer — Bengaluru | strict_recent | uncertain | We are looking for exceptional ML/NLP engineers to join our team. | [job](https://jobs.ashbyhq.com/Wisdom-AI/35029bbd-c8cd-448a-8491-65ea639dbea2) |

## Evidence quality and usage

- Completed decisions with locally verified verbatim description evidence: 28.
- Requests: 28; estimated input tokens reserved: 21065; measured input tokens: 18523; measured output tokens: 3715.
- No monetary estimate is claimed because the corporate gateway chargeback policy is not available.

## Review requested

The user approved the recommended first-release threshold and uncertainty policy without
case-labelled corrections on 2026-09-23. Prompt `1.0.1`, evaluation set `1.0.0`, and the metrics in
this artifact are the approved Phase 8 baseline.
