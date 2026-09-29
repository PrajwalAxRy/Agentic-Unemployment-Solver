# to_change.md — agreed changes, not yet built

Running record of decisions from the design discussion. Still **no code written yet**, but
as of 2026-09-30 the design is closed: every open question has an answer, and the build
order is fixed in the phase list below.

Status key: **DECIDED** settled · **DEFERRED** revisit later (with a stated trigger)

**State of play (2026-09-30):** §9 records standard solutions for twelve mechanical items;
§10 closes decisions A–F. Nothing is awaiting a call. Next action is Phase 0.

---

## Index

**1. Bugs to fix first** — all DECIDED, blocking everything else
- 1.1 Surface swallowed errors (`scan.py:517`) — do this *before* 1.2
- 1.2 Title-normalization mismatch — fatal in 10 adapters; duplication is near-total (→6.3)
- 1.3 Fix the test that hid it

**2. Pipeline restructure** — all DECIDED
- 2.1 Location before title · 2.2 Title → non-engineering blocklist · 2.3 Relevance → LLM
- **2.2a The actual blocklist — ✅ BUILT & VALIDATED, `prototypes/title_filter.py`**
- 2.4 Simplified remote · 2.4a Source-side geo filter — ✅ leave as-is, known blind spot
- 2.5 One merged LLM call · 2.6 Three-way verdicts

**3. Daily runs and lifecycle** — all DECIDED
- 3.1 Job-ID lifecycle · 3.2 Staleness (3 absences) · 3.3 Never expire on failure
- 3.4 Discovery integrity · 3.5 Two-month window · 3.6 "New" keys on verdict
- 3.7 Scan delta vs site window

**4. Schema** — all DECIDED
- 4.1 New columns · 4.2 Single table · 4.2a Days-active · 4.3 Wipe (deferred execution)

**5. Rollout safety** — all DECIDED
- 5.1 Expiry dry-run · 5.2 Rate limiting · 5.3 Reappearance monitoring


**6. Engineering audit findings** (2026-09-30) — codebase-level issues found in review
- 6.1 No logging at all · 6.2 85 error-discarding handlers · 6.3 Shared normalization unused
- 6.4 ~2,300 LOC duplicate helpers · 6.5 Parallelization · 6.6 Adapter contract gaps
- 6.7 ~4,100 LOC frozen scaffolding · 6.8 `filter_verification.py` misnamed
- **6.9 Identity-hash migration hazard — affects wipe sequencing (4.3)**

**7. Explicitly deferred** — model choice, eval set, website schema, 180-company backlog,
build order

**9. Resolutions applied (2026-09-30)** — standard solutions for 12 items; no further
discussion needed

**10. Decisions A–F** — ✅ all six closed 2026-09-30, with the reasoning kept

**11. Known-unresolved rows** from the 2026-09-29 scan — recheck after the clean re-run

---

## Revised priority (post-audit, re-phased 2026-09-30)

Design decisions in §2–§5 are unchanged; the audit reorders *implementation*. Items marked
✅ have a settled standard solution recorded in §9 and need no further discussion.

**Phase 0 — make failure visible.** Nothing downstream is verifiable until this lands.
- ✅ 6.1 logging · ✅ 6.2 bind the 85 discarded exceptions · ✅ 1.1 exception taxonomy
- ✅ 1.3 regression test through the real call path
- Treat as one unit, not four: the taxonomy is what makes the logs legible.

**Phase 1 — root-cause fix, one pass over the adapters.**
- ✅ 1.2 + 6.3 — delete local copies, import `job_finder.normalization.jobs`
- ✅ 6.8 rename `filter_verification.py` → `collection.py`
- ✅ 6.4 (conservative scope — `adapters/_support.py` + `core/validation.py`)
- 6.4 full template-method rewrite → ✅ **deferred until after the backlog lands** (10.C)
- Rationale for merging: 6.4 and 6.8 touch the same 36 files 6.3 already opens. Sequencing
  them separately means churning every adapter twice and re-reviewing the same diffs.

**Phase 2 — scale and integrity.**
- ✅ 6.6 completion reason (`exhausted` / `page_cap_reached` / `truncated`) — prerequisite
  for 3.4, and the audit's priority list omitted it
- ✅ 6.6 per-host rate limiting + honor `retry_after_seconds` · ✅ 5.2
- ✅ 6.5 parallelization (after Phase 0 — thread pools swallow exceptions even harder)
- ✅ 6.6 capability flags cross-validated against registry `detail_strategy`

**Phase 3 — pipeline behaviour.**
- ✅ 2.1 location before title (must precede the title-filter swap)
- ✅ 2.5 merged LLM call · ✅ 2.3 LLM relevance gate · ✅ 2.6 three-way verdicts
- ✅ 2.2a integrated *after* the LLM gate and rate limiter (decision E) — it is already
  built, but shipping it first makes a scan you cannot afford to finish
- ✅ model: configured `gpt-5.6-luna` (decision D); measure cost at integration

**Phase 4 — lifecycle, then the wipe.**
- ✅ §3 lifecycle · ✅ §4.1/4.2/4.2a schema columns
- ✅ 4.3 wipe — *after* the schema columns, not just after normalization (see 9.10)
- ✅ 5.1 expiry dry-run · ✅ 5.3 reappearance monitoring

**Unscheduled / independent.**
- ✅ 2.4a source-side geo filter — **leave as-is** (decision A); recorded as a known blind
  spot in `PS_Note.md`. See 10.A.
- **Backlog rollout (180 companies) — after Phase 2.** 174 of the 180 are `search_only`,
  i.e. no adapter exists yet, so this is *writing* adapters, not refactoring them. It must
  follow the Phase 1 extraction (or each new adapter re-creates the duplication) and the
  Phase 2 rate limiting/parallelization (or 330 companies is ~114 min sequential). See 10.C.
- ✅ 6.7 frozen scaffolding — **move to `scripts/`** (decision B). Do this *before* Phase 1,
  since it anchors `filter_verification`'s API and would otherwise constrain the 6.8 rename
  and 6.4 extraction happening there.
- §8 unresolved rows — genuinely wait for the clean re-run

---

## 1. Bugs to fix first

### 1.1 Surface swallowed errors — DECIDED
*(Expanded 2026-09-30 after codebase audit — this is a pattern, not one line. See 6.1/6.2.)*

`scan.py:517` catches `ValueError` and returns a bare `description_unavailable` with no
reason. This is why a trivial punctuation bug survived across ten adapters and 97 rows
looking like a network failure.

**Root cause is deeper than the catch site:** `get_job_detail` uses `ValueError` as its
*assertion vocabulary*, not just its parse-error vocabulary. `google_careers.py` raises
`ValueError` from six distinct checks — title mismatch, URL identity mismatch, response-URL
mismatch, missing India location, empty required section, detail-ID mismatch. All six
collapse into the same string. A 403 and "Google changed a heading" are indistinguishable.

Fix properly: introduce distinct exception types (e.g. `DetailUnavailable` vs
`DetailIdentityMismatch`) so the catch site *can* tell them apart, then bind `as error` and
record `type(error).__name__` + message into the existing `reason_code` /
`exception_category` fields — the report schema already has slots for them.

Same swallow pattern at `filter_verification.py:264`, `filter_verification.py:282`,
`seniority_validation.py:259`, `seniority_validation.py:663`, and the broadest at
`verification.py:230` (bare `except Exception`, records only the literal string
`"unexpected_adapter_error"`).

Expect the Google 78 to resolve into two or three named causes immediately.

**Do this before 1.2** — otherwise the fix can't be verified and the next bug hides too.

### 1.2 Title-normalization mismatch — DECIDED
*(Scope corrected 2026-09-30 after codebase audit — worse than first recorded. See 6.3.)*

`adapters/google_careers.py:296` compares local `_normalize_text` (keeps punctuation)
against `job.title_normalized`, which `normalization/jobs.py:53` has already
punctuation-stripped. Any title with a comma, hyphen, slash, or parenthesis fails the
identity guard — i.e. most real AI/ML titles. Hit 78/78 Google rows.

Reproduced:

| Title | shared `normalize_title` | adapter `_normalize_text` | match |
|---|---|---|---|
| `Senior ML Engineer, Ads` | `senior ml engineer ads` | `senior ml engineer, ads` | **no** |
| `Staff Engineer (AI/ML)` | `staff engineer ai ml` | `staff engineer (ai/ml)` | **no** |
| `ML Engineer II` | `ml engineer ii` | `ml engineer ii` | yes |

Fatal in ten adapters: `aganitha_careers:224`, `airbnb_careers:370`, `apple_jobs:324`,
`atomicwork:289`, `google_careers:296`, `index_exchange:142`, `microsoft_careers:315`,
`pcsx_careers:232`, `stripe_careers:225`, `twilio_careers:247`.

**But the duplication is near-total, not limited to ten** — see 6.3. Fix at the root by
deleting local copies and importing the shared module, not by patching ten call sites.

⚠ **Sequencing hazard:** this changes the job identity hash. See 6.9 before implementing.

### 1.3 Fix the test that hid it — DECIDED
`tests/adapters/test_google_careers.py:116` passes because it feeds `get_job_detail` a raw
listing, never routing through `normalize_job()` — it bypasses the exact transformation
that breaks production. Regression test must exercise the real call path.

---

## 2. Pipeline restructure

### 2.1 Reorder: location before title — DECIDED
Location is far more selective and unambiguous. Running it first keeps ~19 Bank of America
US/10+yr rows out of the review queue entirely (~25% of the current 128).

Location-review rows still get title-filtered before surfacing, or the queue fills with
irrelevant roles that merely lacked a location.

### 2.2 Title filter inverted to a non-engineering blocklist — DECIDED

**Today's behaviour** (`filters/roles.py`, 5 checks in order, first hit returns):
1. 31 `title_exclusions` → REJECT
2. 8 role families / 68 exact phrases → EXPLICIT_PASS
3. generic title + AI token anywhere → EXPLICIT_PASS ← **the false-positive path**
4. generic title, no AI token → CONDITIONAL_DESCRIPTION (only path reaching the relevance
   gate; fired 10 times all scan)
5. engineering title + AI token → EXPLICIT_PASS
   else → REJECT

Keeps 11% (22,870 → 2,521). The generosity is inverted: **strict** on real ML roles whose
titles don't say "AI" (e.g. "SDE, Ranking Platform" — rejected, never fetched, never seen),
**loose** on anything with "AI" as a token, including a team name. `_TITLE_TOPIC_TERMS`
ending in bare `"ai"` / `"ml"` is the specific culprit; that's how "DevOps Engineer II, Ads
AI Core Infra" got an unconditional pass and skipped the description check.

**New behaviour — allowlist becomes blocklist.** Pass any engineering/technical IC role
(software engineer, SDE, backend, frontend, full stack, DevOps, SRE, data engineer,
platform, infrastructure, data/applied/research scientist…). Reject non-engineering
functions: sales, marketing, recruiting, HR, finance, legal, support, warehouse.

- No title may grant a pass or skip the relevance gate. Checks 3 and 5 die as pass paths.
- Keep the 31 exclusions — cheap and correct ("data labeler", "ai evaluator").
- Keep the 8 role families as **labels**, not gates — useful report metadata and the seed
  for future domain classification (see PS_Note.md).
- No AI-specific logic in this stage at all. Title = discipline; description = domain.

**Volume:** location now runs first (2.1), so this loosening multiplies an already-small
India-eligible set. Estimate ~1,500–2,500 descriptions per full scan vs 106 today — a
one-time cost; daily steady state is the delta, and the description-hash cache absorbs
repeats.

**Management titles: keep them.** "Engineering Manager, AI/ML Infrastructure" passes the
title stage; the seniority gate rejects it. Not excluded by title — that keeps seniority
as the single place experience level is decided, which is what makes multiple seniority
levels easy to add later (see PS_Note.md).

### 2.3 Relevance becomes an LLM gate — DECIDED
The regex gate (`filters/description_relevance.py`) ran **10 times in the entire scan**
(`conditional_pass_count: 5`, `conditional_rejection_count: 5`). It was never the real AI
filter — title substring matching was.

Replace with a mandatory description-based LLM judgment that nothing can skip. Must ask
what the *engineer actually does*, not whether the posting mentions AI.

Encode the four observed failure modes as explicit negatives:
- AI in the org blurb, absent from duties and quals (RBS Tech, GO-AI)
- AI as a tool the engineer uses ("generative AI to improve team productivity")
- AI in the team name only (Ads AI Core Infra)
- AI-assisted development vs AI products ("Native-AI SDLC" — the FBA rows)

### 2.4 Simplified remote handling — DECIDED
Collapse four config knobs into one model judgment.

At location stage: pass on explicit India **or** any unqualified remote (bare "Remote",
"Remote - India", "Remote (APAC)"). Keep deterministic rejection for remote with an
explicit non-India geography ("Remote - United States") — no model call needed.

Remote-unresolved rows carry a flag; the LLM decides India eligibility from the description.

Retire: `remote_requires_explicit_country`, `accept_unqualified_remote_alternative`,
probably `ambiguous_location_treatment`.

### 2.4a Source-side geo filtering bypasses the remote policy — ✅ DECIDED: LEAVE AS-IS

> **Decision 2026-09-30: keep the country filter, accept the blind spot, move on.**
> Removing it means crawling Amazon's entire global inventory for a possibly-zero payoff,
> and coverage is not the current bottleneck. Recorded as a known limitation in
> `PS_Note.md` so it isn't rediscovered as a bug later.
>
> If it ever needs revisiting, the test is unchanged: fetch one unfiltered page from
> Amazon/Google/Apple and count remote-India-eligible roles.

`adapters/amazon_jobs.py:346` rejects any job where `country_code != "IND"`, **inside the
adapter**. Those jobs never reach the location filter, so the remote handling in 2.4 never
runs for Amazon. `accept_unqualified_remote_alternative = true` is silently overridden
upstream.

⚠ **Correction 2026-09-30 (read the code):** this is not a silent drop — line 346 `raise`s,
and the caller records it as a **`malformed_job` diagnostic**. Non-India jobs are therefore
miscategorised as corrupt source data. That is worse than a silent drop: it pollutes the
exact signal that is supposed to tell you an adapter has broken. Also note the config URL
already carries `country=IND` (`config/company_sources.json:725`), so the adapter check is
a redundant second guard.

Scope: only 3 of 150 enabled sources filter geography at the source —
- `google` — `?location=India`
- `amazon-aws` — `?country=IND` **plus** the adapter-level drop
- `apple` — `?location=india-INDC`

The other 147 fetch broadly and let the filter layer decide (correct design).

Unresolved tension: removing Amazon's country filter means crawling their entire global
inventory (tens of thousands of listings) to find possibly-zero India-eligible remote roles.
Before deciding — (a) check whether Amazon's search exposes a remote-eligible flag that can
be queried alongside the country filter, and (b) sample an unfiltered slice from all three
to measure whether India-eligible remote roles exist in any quantity. Google/Apple use URL
params rather than adapter code, so their remote behaviour depends on how each site treats
remote roles under a location filter — needs checking separately.

**Principle regardless of the outcome: filtering belongs in the filter layer, not inside
adapters.** A hard drop at adapter level is invisible to every metric — no count, no review
queue, no rejection reason. Same class of silent loss as the normalization bug. If the
country filter stays for cost reasons, express it as configuration the filter layer knows
about, not a bare comparison in adapter code.

### 2.2a The actual blocklist — ✅ BUILT AND VALIDATED (2026-09-30)

> **Working prototype: `prototypes/title_filter.py`**
> **Test suite: `prototypes/test_title_filter.py`** — run it; all three layers pass.
> Not yet wired into `filters/roles.py`; that's the integration step.
>
> Validated against: 77 hand-written cases (each from a real bug), 1,300 live Amazon
> India titles, 1,120 Greenhouse titles across 14 companies, and all 130 titles that
> passed the old filter in the real 2026-09-29 scan.
> **Result: 0 false negatives, 0 regressions.** Pass rate 79% Amazon / 70% Greenhouse
> (vs 11% today).
>
> Two adversarial review passes (~700 constructed titles) found 8 bug classes, all fixed.
> The history below is kept because each entry is a trap worth not re-entering.

**Two distinct failure modes found:**

**(a) Sub-word matching.** `"pr"` matched inside **Prime**, `"ui"` inside **Build
Intelligence**, `"hr"` inside arbitrary words. Fix: word-boundary matching (`\b`), never
bare substring.

**(b) Domain-vs-function confusion — the serious one.** Blocklist terms describe the
*business domain the engineer works in*, not the job function. Real titles wrongly blocked:

| Title | Blocked on |
|---|---|
| `Machine Learning Engineer, Prime Video Ads CX` | "pr" in Prime |
| `Software Dev Engineer II, AWS Healthcare AI` | "health" |
| `Software Development Engineer, Amazon Customer Service` | "customer service" |
| `Software Dev Engineer II, Amazon Marketing Cloud` | "marketing" |
| `Data Scientist II, EU Prime and Marketing Analytics & Science` | "marketing" |
| `Security Engineer, Security for Employee and Legal Systems` | "legal" |
| `Applied Scientist, Prime Video - Content Reasoning` | "pr" in Prime |
| `Software Development Engineer II, Enterprise Engineering` | "pr" in Prime |

That last one **reached the final report in the real 2026-09-29 scan** — the proposed filter
would have silently dropped it. Word boundaries fix (a) but NOT (b): "customer service" is a
genuine two-word match.

**Required design — engineering-function check takes precedence:**
1. If the title contains an engineering function word (engineer, developer, scientist,
   architect, sde, programmer, …) → **PASS, blocklist not consulted at all.**
2. Only titles lacking a function word are tested against the blocklist.
3. Word-boundary matching throughout.

This fixes every false negative above (all contain "Engineer" or "Scientist"). Residual
ambiguity — "Technical Program Manager", "Delivery Consultant", "Solutions Architect" —
has no function word; per the recall preference these should **pass** and let the LLM decide.

**Final architecture (5 tiers, first hit wins):**
1. **Hard exclusions** — "Data Annotator", "AI Evaluator", "Prompt Writer". Skipped when a
   strong engineering term OR a build-word is present, so "Data Annotation Platform
   Engineer" (builds the system) survives while "Data Annotator" (performs the work) does not.
2. **Engineering terms** → PASS, blocklist never consulted. Includes AI vocabulary,
   hardware/VLSI/embedded, and abbreviations.
3. **Blocklist** — non-engineering *functions* only.
4. **Domain qualifiers** — reject only when no technical noun present. This is what lets
   "Analytics Lead - Tax" through while rejecting "Tax Manager".
5. Otherwise → PASS as ambiguous; the LLM decides.

**Bug classes found and fixed** (each is a regression test now):
- *Sub-word matching* — "pr" matched inside **Prime**, "ui" inside **Build Intelligence**.
  → word-boundary matching throughout.
- *Domain-vs-function* — "Software Dev Engineer II, Amazon **Marketing** Cloud" rejected.
  → engineering check takes precedence.
- *Engineering homonyms in the blocklist* — bare `designer`, `driver`, `controller`,
  `interpreter`, `communications` wiped out **the entire semiconductor/embedded category**
  (RTL Designer, SoC Designer, Device Driver Lead, Flight Controller). → removed and
  disambiguated ("graphic designer", "delivery driver", "financial controller").
- *`strong_eng` used only the FIRST match* — "ml"/"ai" sit early in the tuple, so
  "AI Evaluator **Test Automation**" reported `ai`, was judged weak, and died despite
  `test` and `automation` being present. → scan all matches.
- *Inflection gate too strict at ≥5 chars* — killed `SDETs`, `SREs`, `MLEs`, `LLMs`,
  `Testing`, which then died on domain qualifiers. → ≥3 chars.
- *Exact matching on technical nouns/build words* — "Credit Model" passed, "Credit
  **Models**" rejected. → inflected matching.
- *Bare "analyst" as an engineering term* — let "Senior Financial Analyst" through.
  → qualified forms only ("data analyst", "systems analyst").
- *`safety specialist` blocked* — "Functional Safety Specialist (ISO 26262)" is a mainstream
  Indian automotive/semiconductor role. → narrowed to "workplace/occupational safety".

**Volume impact:** 79% Amazon / 70% Greenhouse vs 11% today. The ~1,500–2,500
descriptions/scan estimate in 2.2 is **too low** — re-measure after integration.

**Known accepted noise** (passes as ambiguous, LLM will drop): "MLS Realtor", "AIS
Coordinator", "Security Guard", "Cloud Kitchen Chef", "Science Teacher". Acceptable by design.

Test data: `prototypes/raw_titles.json` (1,300 Amazon India, all categories),
`prototypes/gh_titles.json` (1,120 Greenhouse, 14 companies).


Clear rejects: sales, marketing, recruiting/talent, HR/people ops, finance/accounting,
legal/compliance, customer support, warehouse/fulfilment/operations, facilities,
communications/PR, plus the existing 31 `title_exclusions`.

> **Resolved 2026-09-30 — the former "edge cases needing a call" list is deleted.**
> It listed technical program manager, solutions architect, developer advocate, QA/SDET,
> technical writer, data/business analyst, security/network engineer, and research intern
> as open questions. The built prototype already answers all of them: tier 2 passes
> anything with an engineering function word (covers SDET, security engineer, network
> engineer, BI engineer, research intern), and tier 5 passes the rest as ambiguous for the
> LLM to judge (covers TPM, solutions architect, developer advocate). That *is* the stated
> recall preference — the title stage is triage, a false positive costs a skim and a false
> negative is invisible. The list was stale text, not a pending decision.

### 2.5 One merged LLM call — DECIDED
Relevance + seniority + location-when-remote in a single call per job, cached on
`description_hash`. Structured schema, separate field and verbatim quote per judgment so
a failing sub-judgment is diagnosable. Omit the location field when location is already
resolved.

Cheap deterministic rejections still happen *before* the model — don't defer them just
because it's one call anyway.

### 2.6 Three-way verdicts, display rule — DECIDED
Every judgment keeps three values. Nothing except a confident rejection is ever dropped —
`unclear` / `peripheral` always display, tiered lower.

Rationale: forcing binary hides uncertainty rather than removing it. A model forced to
pick will pick, and you lose the signal showing which rows deserve a click. Collapse at
render time if desired, but keep it in the data.

Terminology: a displayed `unclear` is the system working. "False positive" means
confident-but-wrong.

---

## 3. Daily runs and lifecycle

### 3.1 Job lifecycle — DECIDED
Job ID only. No repost tracking (see PS_Note.md for why). Track first seen, closed,
days active.

### 3.2 Staleness detection — DECIDED
Absence decides, probing confirms:
- Absent 1 day → probe the URL
- 404/410 → close immediately
- Resolves but missing from listings → mark live-but-missing, close after 3 days
- Timeout / 429 / 503 → **no information**, advance nothing
- **3 consecutive absences closes a job** (revised down from 5)

Because 3 absences closes a job, any survivable gap is ≤2 days. That bound is what makes
the single-table schema safe (see 4.2) — no reconstructable history is lost beyond a
couple of days.

Consequence of the tighter threshold: less tolerance for a *degraded* source — one that
returns results and passes the sanity check but silently drops listings for three straight
days would close real jobs. The probe step is the backstop (a live URL routes to the
3-day soft-close rather than an immediate close), so **the probe must genuinely run on
first absence** — it's load-bearing at 3 days in a way it wasn't at 5.

Also check page text for "no longer available" (many boards serve that with a 200) and
treat redirect-to-search as closed.

### 3.3 Never expire on failure — DECIDED
Three layered guards:
1. Absences only count when the company's scan succeeded. On failure, counters **freeze**
   (not reset).
2. Sharp single-run drop in a company's listing count → run untrusted, excluded from expiry.
   This is the guard against the catastrophic case.
3. A job needs ≥2 confirmed sightings before it's eligible to expire at all.

### 3.4 Discovery integrity — DECIDED
Absence only means absence if discovery was complete. Pagination must be provably complete,
not best-effort — assert against source-reported totals where exposed; treat mismatch as a
failed scan, not a successful partial. Detect silent truncation (run ending exactly on a
page boundary). Distinguish legitimate empty (Deeptune, Compass, Rapido) from broken-adapter
empty.

*Already happened once:* the first 2026-09-29 run hit a transient Workday problem; targeted
verification then returned 378 jobs across 19 pages. Under automated expiry that partial run
could have closed live jobs.

### 3.5 Two-month window — DECIDED
Posted date where the company provides one, `first_seen_at` otherwise. **Store which basis
each row used** — can't be added retroactively, and `first_seen_at` isn't trustworthy until
daily runs have been clean for a while.

### 3.6 "New today" keys on verdict, not first sighting — DECIDED
Feed sorts on `verdict_at` — first time a job reached a qualifying verdict. Display the
posted date.

Critical: rows stranded by the normalization bug have old `first_seen_at`. Keying the feed
on first sighting would mean the ~78 recovered Google roles never appear as new.

### 3.7 Scan delta vs site window — DECIDED
Keep separate. The scan processes what changed since yesterday; the site reads the rolling
two-month window. One query for both means reprocessing old jobs daily.

---

## 4. Schema

### 4.1 New columns — DECIDED
`status` (active/closed), `closed_at`, `consecutive_absences`, `probe_state`, `verdict`,
`verdict_at`, date-basis flag. Days-active is computed, not stored.

Also persist `required_experience` — the normalized requirement string the seniority prompt
*already* returns ("3+ years", "PhD + 4"). Not future-proofing: the model is already paying
to produce it, and showing it in the report tells you at a glance whether an `uncertain`
row is worth a click.

Dropped: `supersedes` (no repost tracking). `fallback_fingerprint` stays as-is — vestigial,
only reachable if a source stops returning job IDs. None currently do: all 859 rows use
`external_id`.

### 4.2 Single table — DECIDED
One row per job. No `observations` history table.

Rationale: with a 3-absence close rule, any gap a job survives is ≤2 days. The history that
gets overwritten is therefore bounded and small, so `first_seen`/`last_seen` describe the
lifecycle accurately to within a couple of days — noise at this granularity.

Still stored as *current state* (not history), because the state machine needs them:
- `consecutive_absences` — so tomorrow's run knows today's count
- `last_probe_result` — the live-but-missing bucket runs on a different clock from plain
  absence

### 4.2a Days-active definition — DECIDED
`days_active = last_seen - first_seen`.

**Display `last_seen` as the closing date, not `closed_at`.** `closed_at` lags by up to 3
days (the absence threshold), so showing it alongside a `last_seen`-derived duration would
put two disagreeing numbers on screen. One date drives both. `closed_at` may still be
stored as an operational record of when detection happened.

### 4.3 Existing 859 rows — DECIDED (deferred execution)
Wipe and start clean. **Not yet** — keep current state until the new pipeline is ready.
(390 technical failures mostly from the normalization bug, 115 pending, all with stale
dates and no absence history.)

---

## 5. Rollout safety

### 5.1 Expiry dry-run — DECIDED (threshold corrected 2026-09-30)
Report-only mode for ~1 week before expiry closes anything for real.

⚠ **This section previously justified the week as "the close rule is 5 consecutive
absences." 3.2 revised that to 3.** The week stands regardless, but for a different and
stronger reason: at 3 absences the *probe* is load-bearing, so the dry-run must exercise
the full state machine, not just the counter. A 3-day run would only just reach a single
close with no margin to observe the live-but-missing branch.

**Dry-run must explicitly verify:**
- the probe genuinely fires on first absence (3.2 calls this load-bearing at 3 days)
- the live-but-missing branch is entered and runs on its own 3-day clock
- timeout / 429 / 503 advance nothing
- the 6.6 `page_cap_reached` completion reason never feeds the absence counter (3.4)

✅ **Threshold decided 2026-09-30: keep 3, gated on the dry-run.** If the probe does not
demonstrably fire on first absence during the dry-run week, revert to 5 until it does. The
real question was never "3 or 5" but "does the probe reliably run" — see 10.F.

### 5.2 Rate limiting — DECIDED
**Exhaustiveness over speed.** A slow scan is acceptable; an incomplete one is not, because
a truncated listing feeds the staleness logic and can close live jobs. On throttling, back
off and retry — never skip ahead.

Parallelize across companies (separate domains, separate limits) while keeping each source
sequential and paced. Defer until the 330-company scale-up; not needed at 150.

### 5.3 Reappearance monitoring — DECIDED
Reappearance is not inherently an error. Legitimate causes: recruiter unpublish/republish,
board freshness rotation, search-index lag behind a live page (Workday, Oracle), job ageing
out of the default view. The probe already handles these — a live URL routes to
live-but-missing rather than closing.

Genuinely anomalous: absent from listing **and** URL 404s **and** later returns.

Track reappearance rate per source and alert on anomalies (a couple a week across 44k
listings is normal; dozens in a day from one company is a bug). That's the code-review
trigger — not reappearance itself, or you'd be investigating normal churn while a real
degraded-source problem hides in the same bucket.

---

## 6. Engineering audit findings (2026-09-30)

Codebase-level review, separate from the pipeline-design decisions above. All figures
verified directly against the repo.

**Headline: the system is structurally incapable of telling you when it breaks.** The
2026-09-29 run reported `outcome: complete` while 92% of description fetches failed.
**Do not automate a daily run until 6.1 and 6.2 are fixed** — a cron job with this error
handling will rot silently for weeks.

**What's genuinely good** (don't break it during refactors): real dependency injection
throughout; the pipeline is fully testable without network or LLM and they actually do it
(15,641 test LOC, stub adapters + stub `SeniorityLLMClient`); `AdapterResult.__post_init__`
enforces real invariants; `BoundedHttpClient` is not a naive `requests` clone — SSRF
validation on every redirect target, response-size cap, honors `Retry-After`, sanitized
errors that never carry credentials. Minimal dependencies is the right call on the HTTP
side. `repair.py` (LLM-assisted source repair, with secret scrubbing) is well-built and
will matter as adapters rot.

### 6.1 No logging anywhere — DECIDED, blocks automation
`import logging` / `getLogger` appears in **zero files** under `src/`. Only observability is
`print()` — 39 calls in `cli.py` plus a `progress: Callable[[str], None]` threaded through
`scan.py:230`, `filter_verification.py:180`, `verification.py`, wired to
`print(message, flush=True)` at `cli.py:733`.

The progress strings are already structured-log-shaped
(`phase=source_collection progress=42/150 company=x outcome=success listings=88`) — reuse
them as the message body. Needs: levels, timestamps, a rotating file sink, and
`logger.exception()` at every catch site. Prerequisite for anything unattended.

### 6.2 85 handlers discard the exception object — DECIDED
`grep "except [^:]*:$" src/ | grep -v " as "` → **85 sites** that bind no variable, so the
error is destroyed by construction. Worst is `verification.py:230` (bare `except Exception`,
records only `"unexpected_adapter_error"` — no type, no message, no traceback).

The isolation intent is right (one broken adapter mustn't hide healthy peers); the execution
throws away everything needed to diagnose it. Bind and record; isolation is preserved.

Also `cli.py:768` catches `RuntimeError`, which swallows `ScanAlreadyRunningError`
(`locking.py:13`) into the same generic `scan=failed` line as a bad config. Under cron with
overlapping runs these need different exit codes.

### 6.3 Shared normalization exists and NOTHING imports it — DECIDED
`grep -rln "from job_finder.normalization" src/job_finder/adapters/` → **0 files**.

Instead: **35 local copies of `_normalize_text`**, **30 of `_normalized_locations`**. The
location helper has drifted into **10 genuinely different implementations** —
`greenhouse.py:352` splits on `[,|;/]|\bor\b` case-insensitively; `jobvite.py:587` splits on
`[,|;/]` only and falls back to `("location unavailable",)`; ashby, intuit, aganitha,
galaxeye each unique. **The same location string produces different tuples depending on
which company the job came from** — and that feeds straight into `filters/locations.py`.

This is the root cause of 1.2, and it is near-total, not limited to the ten fatal sites.
Fix: delete the local copies, import `job_finder.normalization.jobs`.

### 6.4 ~2,300 LOC of duplicate helpers — DECIDED
**Correcting an earlier assumption:** there is no per-company adapter duplication. Every
ATS platform already has exactly one parameterized adapter — 39 Greenhouse companies share
one, 28 Ashby, 25 Workday, 13 Lever. That's good design, already done. The 22 `custom`
adapters are genuinely bespoke (21 serve a single company; Amazon/Google/Apple hand-roll
private APIs — irreducible).

The duplication is **horizontal**: ~500 lines of identical utility tail in every adapter.
2,331 of 19,641 adapter LOC (11.9%) — `_diagnostic`, `_result`/`_failed_result`,
`_request_outcome`, `_required_string`, `_optional_string`, `_plain_text`,
`_unique_strings` = 204 definitions across 36 files. Naming has already drifted
(greenhouse/ashby `_failed_result` vs lever `_result`+`_diagnostic`; `_result` bodies hash
into 3 variants).

Separately, **`_required_string` is defined 36 times across `src/`** with subtle divergence
(some take a `path` arg, some raise `GatewayProviderError` instead of `ValueError`) —
~150 hand-written validators total. A single `core/validation.py` removes ~800–1,000 LOC.
**No new dependency needed** — this is not an argument for Pydantic.

Target: extract `adapters/_support.py`; make `list_jobs` a template method so adapters
supply only `_normalize_job`, the URL builder, and the date parser (~120–180 genuinely
specific lines). Realistic: ~500 → ~200 LOC per adapter, 19,600 → ~8,000.

### 6.5 Fully sequential; parallelization is unusually easy — DECIDED, after 6.1/6.2
`grep -rn "ThreadPool\|concurrent.futures\|asyncio\|threading" src/` → **0 hits**.
150 companies / 3,108s ≈ **20.7s per company**, essentially all blocking I/O. At 330 that's
~114 min.

The structure is ready: `filter_verification.py:196-222` builds a pending list with *zero*
filtering, then 228-342 is pure CPU over that list — only the first loop needs
parallelizing. Adapters are stateless (hold only `self._client`); parsers are instantiated
per-call; `HttpPolicy` is frozen and `UrllibTransport` builds a fresh opener per request, so
the client is thread-safe; all SQLite access happens afterward under `ScanLock`.

A bounded `ThreadPoolExecutor` over `enabled_entries`, results sorted by `source_rank` for
determinism. Realistically 51 min → 10–15 min.

**Must come after 6.1/6.2** — thread pools swallow exceptions even more thoroughly than bare
`except` (`Future.result()` re-raises only if called). Also needs the per-host rate limiter
(5.2) and a thread-safe progress callback.

### 6.6 Adapter contract gaps — DECIDED
`base.py` / `source_contracts.py` are the strongest part of the codebase, but three gaps
matter at 330 companies:

- **No per-host rate limiting.** `HttpPolicy` (`http_client.py:34-55`) has timeout/retry/
  backoff but no `min_interval` or concurrency cap. 39 Greenhouse companies hit
  `boards-api.greenhouse.io` back-to-back. `HttpRequestError.retry_after_seconds` is
  captured but **no adapter honors it**, and `list_jobs_with_retry` (`base.py:68`) retries
  immediately with no delay — it will amplify a 429 into a block. Directly relevant to 5.2.
- **`complete` is a bare bool conflating "no more pages" with "hit my cap."** Only 17 of 36
  adapters define a page cap, and values are unreviewed copy-paste (`DEFAULT_MAX_PAGES` 100
  in 9 files, 500 in 3; `_MAX_PAGES` 10/50/100; `_PAGE_SIZE` 10–200). **This directly
  undermines 3.4** — silent truncation is indistinguishable from an exhausted board, and
  under the new staleness logic that closes live jobs. Replace with an explicit completion
  reason: `exhausted` / `page_cap_reached` / `truncated`.
- **No capability flags.** Detail support is discovered via `isinstance` at `scan.py:510`.
  The registry declares `detail_strategy` per source (191 `detail_page`, 92
  `listing_payload`, 41 `detail_endpoint`) but nothing cross-validates config against the
  implementation — mismatches fail at runtime.

### 6.7 ~4,100 LOC of frozen phase-gate scaffolding — ✅ DECIDED 2026-09-30: move to `scripts/`
Not dead code — all typed, tested, and reachable via CLI subcommands — but none of it runs
during a daily scan:

- `seniority_validation.py` (820) — docstring: *"Guarded Phase 8 live validation and H9
  review reporting."* Generates `docs/reviews/h9_seniority_quality_review.md`. Types named
  `Phase8ValidationReport`. A one-time phase-gate artifact generator in the shipped wheel.
- `persistence_verification.py` (230) — runs `verify_filters` **twice** against a disposable
  DB to prove idempotency. A ~100-minute test, shipped as a CLI command.
- `recency_verification.py` (495) — full 150-company network sweep for a coverage report.
  Nothing in `scan.py` imports it.
- ~2,600 LOC in `core/` (`source_discovery` 408, `adapter_validation` 566, `source_probe`
  268, `search_discovery` 316, …) imported **only** by `scripts/` and `tests/`.

**Decision: move to `scripts/`.** A ~100-minute idempotency test and a one-time phase-gate
report generator are not wheel material, and they currently anchor `filter_verification`'s
API so it cannot be refactored freely. **Do this before Phase 1** — otherwise it constrains
the 6.8 rename and 6.4 extraction happening in that same pass.

Keep them runnable and tested; this is a relocation, not a deletion. Tests move with them.

### 6.8 `filter_verification.py` is misnamed — DECIDED
Despite the name it is **not** verification. `verify_filters()` (line 171) fetches every
company, normalizes, and applies recency/role/location filters. `scan.py:254` calls it as
step one of every scan. It is the hottest code in the repo (725 LOC) and the name reads as
optional QA. Rename to `pipeline.py` or `collection.py`.

Also: `cli.py` (840) is doing three unrelated jobs — a hardcoded DI container
(`_runtime_adapters` 458-502 instantiates all 36 adapters literally, and `AdapterType`
values are *separately* hand-listed in `--adapter` choices at 131-147, which will drift),
report formatting (~39 `print()` f-strings that belong next to `reporting/scan_report.py`),
and business logic (`_validate_seniority` 611-730 is 120 lines of pipeline orchestration in
the arg-parsing layer).

### 6.9 Identity-hash migration hazard — DECIDED
⚠ Fixing 1.2/6.3 changes `title_normalized`, and `persistence/identity.py:92` uses
`normalize_title` in the identity hash. This **re-keys every stored job** and produces a
one-time burst of false "new job" results.

**Mitigation: do the 4.3 wipe AFTER the normalization fix, not before.** Verify whether the
identity path is already consistent before migrating.

---

## 7. Explicitly deferred

- **Model choice** — ✅ **DECIDED 2026-09-30: stay on the currently configured
  `gpt-5.6-luna`.** Prompts can change meanwhile; revisit with the eval set before
  committing to anything else.
  **Caveat to watch:** 2.2a raises the pass rate from 11% to 70–79%, so the number of
  description-level LLM calls per scan rises by roughly an order of magnitude. Measure
  actual per-scan cost and latency at 2.2a integration (Phase 3). If it bites, the first
  lever is the `description_hash` cache hit rate, not a model swap.
- **Eval set extension** — leave as-is for now.
- **Website schema** — wait until the scanner's output shape settles.
- **180-company backlog** — ✅ **scheduled 2026-09-30: after Phase 2, before the large 6.4
  rewrite.** Still don't touch until the pipeline is stable, or you're debugging new
  adapters and new logic at once. Triage by rendering type first: Atlassian is fully
  JS-rendered and unreachable without a headless browser.
  Measured shape: **174 of the 180 are `search_only`** (no adapter exists yet) and 178 are
  `status: proposed`. This is adapter-*writing* work, not refactoring — which is exactly
  why it must follow the Phase 1 `_support.py` extraction. See 10.C.
- **Repost tracking** — dropped; retroactively computable if it ever matters.
- **Build order** — to be settled once the design is final.

---

## 9. Resolutions applied 2026-09-30 (standard solutions, no further discussion needed)

Each item below had a generic or strongly-recommended answer. Recorded here so they stop
consuming decision attention. Open questions are in §10.

### 9.1 Logging (6.1) — stdlib `logging`, no dependency
`logging.getLogger(__name__)` per module. Configure once in `cli.py` only — libraries
configure no handlers. `RotatingFileHandler` to `state/logs/scan.log` (10 MB × 5) plus a
stderr handler; stdout stays clean for report output.

The existing `progress: Callable[[str], None]` stays as the *user-facing* channel — do not
delete it. Wire a second sink so each progress string is also logged at INFO. The strings
are already `key=value`-shaped, so they need no reformatting.

Levels: DEBUG per-job, INFO per-company/phase, WARNING recoverable-and-recorded, ERROR
company failed, CRITICAL scan cannot continue. Every catch site that currently swallows
gets `logger.exception(...)` — it captures the traceback automatically and is the standard
call inside an `except` block.

### 9.2 Exception binding (6.2) — bind and record, keep the isolation
Mechanical: `except X:` → `except X as error:`, then `logger.exception` plus
`type(error).__name__` and `str(error)` into the existing `reason_code` /
`exception_category` slots. The isolation intent is correct and is preserved — a broken
adapter still must not hide healthy peers. All 85 sites, no judgment required per site.

`verification.py:230`'s bare `except Exception` keeps its breadth (last-resort boundary
handler, which is legitimate) but must record type + message + traceback instead of the
literal string `"unexpected_adapter_error"`.

### 9.3 Exception taxonomy (1.1) — split assertion from parse failure
`get_job_detail` currently overloads `ValueError` as its assertion vocabulary. The six
`google_careers.py` raises are two distinct kinds:

| Line | Check | New type |
|---|---|---|
| 271 | detail job ≠ configured source | `DetailIdentityMismatch` |
| 274 | detail URL identity ≠ listing | `DetailIdentityMismatch` |
| 290 | response URL ≠ listing | `DetailIdentityMismatch` |
| 297 | detail title ≠ listing title | `DetailIdentityMismatch` ← the 78-row bug |
| 300 | no India location | `DetailContentMissing` |
| 313 | required section empty | `DetailContentMissing` |

Base `DetailUnavailable(ValueError)` so existing catches keep working during migration;
`DetailIdentityMismatch` and `DetailContentMissing` subclass it. Subclassing `ValueError`
follows the codebase's own precedent (`AdapterConfigurationError`, `SeniorityResponseError`,
`_RemoteApiError` all do this).

`scan.py:517` binds `as error` and records `type(error).__name__`. A 403 and "Google moved
a heading" become distinguishable, which is the whole point.

Also split `ScanAlreadyRunningError` out of the `cli.py:768` `RuntimeError` catch and give
it a distinct exit code — under cron, "already running" is benign and "bad config" is not.

### 9.4 Normalization canon (1.2 / 6.3) — one module, delete 65 copies
`src/job_finder/normalization/jobs.py` already exports `normalize_text`, `normalize_title`,
`normalize_location_values`, `canonicalize_job_url`, `parse_source_timestamp`,
`normalize_job`. Zero adapters import it. Delete the 35 `_normalize_text` and 30
`_normalized_locations` local copies and import the shared ones.

The location helper is the higher-risk half: 10 genuinely divergent implementations mean
the same string yields different tuples depending on source, feeding `filters/locations.py`.
Note the shared `normalize_location_values` takes a `LocationPolicy`, which the local copies
do not — so alias handling changes too. Expect location-filter output to shift; that is the
fix working, not a regression.

Add a lint guard (ruff/grep in CI) banning re-definition of these names under `adapters/`,
or the copies grow back.

### 9.5 Regression test (1.3) — exercise the real path
`tests/adapters/test_google_careers.py:116` feeds `get_job_detail` a raw listing, bypassing
`normalize_job()`. Rewrite to route through it, and parametrize over the reproduced cases —
`Senior ML Engineer, Ads`, `Staff Engineer (AI/ML)`, `ML Engineer II`. Apply the same shape
to all ten fatal adapters. Assert on the new specific exception types from 9.3, not on
`ValueError`, or the test passes for the wrong reason again.

### 9.6 Completion reason (6.6) — replace the bare bool with an enum
`AdapterResult.complete: bool` conflates "board exhausted" with "hit my page cap".
Confirmed in code: `lever.py:222-236` appends a `pagination_limit` diagnostic and returns
`SUSPICIOUS` on cap — good — but the bool itself cannot express it, and page caps are
unreviewed copy-paste (`DEFAULT_MAX_PAGES` 500 in workday, 100 in lever, `_MAX_PAGES`
10/50/100 elsewhere).

Add `CompletionReason` enum: `EXHAUSTED` / `PAGE_CAP_REACHED` / `TRUNCATED` /
`INCOMPLETE`. Keep `complete` as a derived property (`reason is EXHAUSTED`) so the existing
`__post_init__` invariants at `source_contracts.py:174-183` keep holding and nothing
downstream breaks during migration.

**Only `EXHAUSTED` may feed the absence counter.** This is the 3.4 prerequisite — without
it, silent truncation is indistinguishable from an exhausted board and closes live jobs.
The audit's revised-priority list omitted 6.6 entirely; that was an oversight.

### 9.7 Rate limiting (5.2 / 6.6) — token bucket keyed by host
`HttpPolicy` is frozen and has timeout/retry/backoff but no `min_interval` or concurrency
cap. 39 Greenhouse companies hit `boards-api.greenhouse.io` back-to-back.

Add `min_interval_seconds` and `max_concurrent` to `HttpPolicy`, enforced by a shared
per-host limiter inside the transport so every adapter inherits it without individual
changes. `HttpRequestError.retry_after_seconds` is already captured and no adapter honors
it — honor it centrally, in the same place.

`list_jobs_with_retry` (`base.py:68`) currently retries immediately with no delay, which
amplifies a 429 into a block. Add exponential backoff with jitter — the standard remedy.

### 9.8 Parallelization (6.5) — bounded `ThreadPoolExecutor`
Blocking I/O, stateless adapters, thread-safe client (fresh opener per request), all SQLite
access afterward under `ScanLock`. `ThreadPoolExecutor(max_workers=8)` over
`enabled_entries`, results sorted by `source_rank` for determinism.

Two standard traps, both mandatory: always call `Future.result()` so exceptions re-raise
rather than vanishing, and guard the progress callback with a `Lock`. Per-host limits from
9.7 do the throttling — worker count is not the throttle.

### 9.9 Rename (6.8) — `filter_verification.py` → `collection.py`
It is not verification: `verify_filters()` fetches every company, normalizes, and applies
filters as step one of every scan. `collection.py` describes what it does;
`verify_filters()` → `collect_listings()`. Mechanical rename, do it in the Phase 1 pass
while the files are already open.

### 9.10 Wipe sequencing (4.3 / 6.9) — after the schema, not just after normalization
6.9 correctly requires the wipe to follow the normalization fix, since
`persistence/identity.py:92` uses `normalize_title` in the identity hash and re-keys every
stored job. Extending that: wipe after the §4 schema columns land too. Wiping first means
re-keying the store twice for no benefit. One wipe, immediately before the 5.1 dry-run
window opens.

### 9.11 Edge-case title list (2.2a) — deleted as stale
See the note in 2.2a. The prototype's tier 2 / tier 5 structure already resolves every
entry; it was leftover text from before the prototype was built.

### 9.12 Dry-run threshold reference (5.1) — corrected
5.1 still cited the old 5-absence rule that 3.2 revised to 3. Corrected in place, with the
explicit dry-run checklist the tighter threshold requires.

---

## 10. Decisions A–F — all closed 2026-09-30

**All six are now closed.**

- **A — 2.4a** geo filter — ✅ **DECIDED: leave as-is, do not remove the country filter.**
  Documented as a known blind spot in `PS_Note.md`. See 10.A for the one thing still worth
  fixing opportunistically (the `malformed_job` miscategorisation).
- **B — 6.7** frozen scaffolding — ✅ **DECIDED: move to `scripts/`,** before Phase 1.
- **C — 6.4** consolidation depth — ✅ **DECIDED: small extraction in Phase 1; backlog
  after Phase 2; large template method deferred until the adapter shape has stabilised.**
  See 10.C — the registry data is what settles this.
- **D — §7** model choice — ✅ **DECIDED: use the configured `gpt-5.6-luna` for now.**
- **E — 2.2a** integration timing — ✅ **DECIDED: integrate after the LLM gate and rate
  limiter exist, not before.**
- **F — 3.2** close threshold — ✅ **DECIDED: keep 3, gated on the 5.1 dry-run
  demonstrating that the probe fires on first absence.** Revert to 5 if it does not.

### 10.A Geo filter — what the sample has to answer

Correction to 2.4a from reading the code: `amazon_jobs.py:346` does not silently drop —
it `raise`s, and the caller books that as a **`malformed_job` diagnostic**. So a non-India
job is miscategorised as corrupt source data rather than counted as a filtered job. That is
arguably worse than a silent drop, because it pollutes the signal that tells you an adapter
has broken.

Note also the config URL already carries `country=IND`
(`config/company_sources.json:725`), so the adapter check is a second, redundant guard.

**The sample:** fetch one page of `amazon.jobs/en/search.json` *without* `country=IND`,
count postings that are remote-and-plausibly-India-eligible. Zero → keep the filter and
close this out. Non-trivial → the 2.4 remote policy is being bypassed for the three largest
sources and needs wiring properly.

**True regardless of the outcome:** the rejection must be expressed as a counted filter
decision, not a `malformed_job` diagnostic.

### 10.C Consolidation depth — ✅ RESOLVED 2026-09-30 (refactor first, backlog after)

**Small:** extract shared helpers to `adapters/_support.py` + `core/validation.py`, adapters
import them. Function bodies unchanged, so the existing suite catches any breakage
immediately. ~1,500 of the ~2,300 LOC, low risk.

**Large:** additionally make `list_jobs` a base-class template method; adapters supply only
`_normalize_job`, URL builder, date parser. ~19,600 → ~8,000 LOC, but rewrites the control
flow of all 36 adapters.

**The question raised: should the 180-company backlog land first, so the refactor covers
everything at once?** Intuitive, but the registry says no. Measured from
`config/company_sources.json`:

| | count | adapter_type |
|---|---|---|
| enabled | 150 | 15 distinct platform adapters (39 greenhouse, 28 ashby, 25 workday, 22 custom, 13 lever, …) |
| backlog | 180 | **174 `search_only`**, 4 `unresolved`, 2 `unsupported` |

**`search_only` means no adapter exists yet — not an adapter waiting to be refactored.**
178 of the 180 are `status: proposed`. So the backlog does not enlarge the surface the
refactor touches; it is 36 adapter files either way.

Three consequences, all pointing the same direction:

1. **The refactor does not get more expensive by waiting, but the backlog gets cheaper by
   not waiting.** Every new adapter written *before* the extraction is another ~500-line
   copy of the same helper tail — i.e. building the duplication the refactor then has to
   remove. Writing 174 adapters first maximises the work.
2. **Doing the backlog first blocks on Phase 0/2 anyway.** 174 new sources without logging
   (6.1), bound exceptions (6.2), rate limiting (5.2/6.6) or parallelization (6.5) is
   exactly the "debugging new adapters and new logic at once" trap §7 already warns about.
   At 20.7 s/company sequential, 330 companies is ~114 minutes per scan.
3. **Coverage is not currently the bottleneck.** The 2026-09-29 run reported
   `outcome: complete` while 92% of description fetches failed. Adding 180 companies to a
   pipeline that silently loses most of its descriptions multiplies the loss.

**Decision: keep the phase order — small extraction during Phase 1, backlog after Phase 2.**
The extraction is what makes adding 174 adapters cheap, so it must precede them. Rough
order: Phase 0 → Phase 1 (small extraction) → Phase 2 (rate limiting + parallelization) →
backlog rollout in batches → revisit the large template-method version once the adapter
shape has stabilised across a much wider sample.

**Bonus from sequencing it this way:** writing 174 adapters against `_support.py` reveals
which abstractions actually generalise. That is far better evidence for designing the
template method than 36 files can give — so the large version gets *easier and better
informed* by waiting, which is the opposite of the usual refactor-debt argument.

### 10.F Close threshold — the real question

Not "3 or 5" but **"does the URL probe reliably fire on first absence?"**

Failure mode: a board silently returns 50 of 200 jobs with no error. Job 150 reads as
absent; three such days close a live posting. The probe is the only guard — a live URL
routes to live-but-missing instead of closing. At 5 absences the probe was a nice-to-have;
at 3 it is the entire safety margin.

**Recommendation: keep 3, but gate it on the 5.1 dry-run.** If the probe does not
demonstrably fire on first absence during that week, revert to 5 until it does.

---

## 11. Known-unresolved rows from the 2026-09-29 scan
*(was §8; renumbered 2026-09-30 when §9/§10 were added)*

Not yet verified, deprioritized in favour of the Amazon false-positive audit:
Adobe frontend role, D. E. Shaw Linux Engineering, 2 Mastercard LLM no-completion failures,
4 missing-location + 2 ambiguous-location cases, 4 seniority-uncertain rows.

Many will resolve themselves once descriptions actually arrive post-fix — recheck after
the clean re-run rather than investigating now.
