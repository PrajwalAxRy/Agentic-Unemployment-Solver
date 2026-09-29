"""Corrected generous title filter — engineering-function check takes precedence.

Design (to_change.md 2.2 / 2.2a):
  1. Hard exclusions: specific non-engineering AI-adjacent roles. Checked FIRST because
     "AI Evaluator" and "Prompt Writer" contain no engineering function word but must
     still be rejected.
  2. Engineering function word present  -> PASS, blocklist never consulted.
  3. Otherwise -> blocklist decides.
  4. No function word, not blocked      -> PASS (ambiguous; let the LLM decide).

All matching is word-boundary based. Substring matching caused "Prime" to match "pr".
"""

from __future__ import annotations

import re

# --- 1. Hard exclusions -----------------------------------------------------
# Non-engineering roles with no engineering function word. These are checked
# first, but ONLY fire when no engineering term and no build-word is present —
# otherwise "Data Annotation Platform Engineer" (an SDE building annotation
# infrastructure) would be killed by the same term as "Data Annotator".
#
# Dropped from this list entirely: "ai account", "ai policy" — not job titles,
# and both are substrings of real roles ("AI Account Takeover Detection
# Engineer", "AI Policy Engine Developer").
HARD_EXCLUSIONS = (
    "data labeler", "data labeller", "data annotator",
    "data annotation", "data labeling", "data labelling",
    "ai evaluator", "model evaluator", "ai rater", "search evaluator",
    "prompt writer", "ai content writer", "ai content reviewer",
    "ai trainer", "ai tutor", "content reviewer",
    "ai recruiter", "ai marketing", "ai governance",
    "ai ethicist", "ai sales",
)

# If any of these appear, a HARD_EXCLUSION match is treated as describing the
# system being built rather than the job function, and the title survives.
BUILD_WORDS = (
    "platform", "tool", "tooling", "infrastructure", "service",
    "pipeline", "system", "engine", "backend",
    "api", "sdk", "runtime", "framework", "workflow", "studio", "portal",
    "app", "ops", "stack", "orchestration", "quality",
)

# --- 2. Engineering function words -----------------------------------------
# If any of these appear as a whole word/phrase, the role is technical enough
# to hand to the LLM. Deliberately broad: recall matters more than precision.
ENGINEERING_TERMS = (
    # core function words
    "engineer", "engineering",
    "developer", "development engineer",
    "programmer", "coder",
    "scientist", "science",
    "architect",
    "sde", "sdet", "swe", "mts", "member of technical staff", "technical staff",
    "technologist",
    "researcher",
    # NOTE: bare "analyst" is deliberately NOT here — it matches "Financial
    # Analyst", "Compliance Analyst" etc. Only qualified technical analysts.
    "data analyst", "business intelligence", "bi analyst", "systems analyst",
    "quantitative analyst", "security analyst",
    "administrator", "sysadmin",
    "devops", "sre", "site reliability",
    # AI/ML vocabulary — without these, an AI title carrying a domain noun
    # (e.g. "NLP Lead - Legal") falls through to the blocklist and dies.
    "data engineer", "ml", "ai", "machine learning", "deep learning",
    "nlp", "natural language", "llm", "genai", "gen ai", "generative ai",
    "computer vision", "perception", "speech", "robotics", "robotic",
    "algorithm", "algorithms", "mlops", "llmops", "mle",
    "statistician", "quant", "quantitative",
    "analytics", "informatics", "bioinformatics", "computational",
    "recommender", "ranking", "personalization", "forecasting",
    # software disciplines
    "full stack", "fullstack", "frontend", "front end", "backend", "back end",
    "mobile", "android", "ios", "web",
    "platform", "infrastructure", "systems",
    "security", "network", "cloud",
    "database", "dba",
    "qa", "quality assurance", "test",
    "technical lead", "tech lead", "software", "technical", "technology",
    "programming", "functional safety",
    # hardware / embedded / silicon — India's semiconductor market is large and
    # these titles frequently lack any of the software function words above.
    "embedded", "firmware", "kernel", "silicon", "vlsi", "rtl",
    "asic", "fpga", "soc", "hardware", "compiler", "runtime",
    # "driver" must be qualified — bare "driver" matches "Delivery Driver".
    "device driver", "kernel driver", "driver development", "display driver",
    "gpu driver", "audio driver", "storage driver", "windows driver",
    "linux driver", "firmware driver", "driver lead", "driver engineer",
    "simulation", "verification", "validation", "optimization", "automation",
)

# --- 3. Non-engineering function blocklist ---------------------------------
# Only consulted when NO engineering term is present. Because the engineering
# check runs FIRST, these can be broad single words without risking a real
# engineering role: "SDE II, Amazon Marketing Cloud" already passed on
# "engineer" and never reaches this list.
BLOCKLIST = (
    # sales & commercial
    "sales", "presales", "account manager", "account executive",
    "business development", "sales representative", "territory manager",
    "quota", "channel manager",
    # marketing & growth
    "public relations", "social media", "copywriter", "content strategist",
    "demand generation", "gtm",
    "marketing communications", "corporate communications",
    # people  ("talent acquisition" / "recruiting" are domain qualifiers, not
    # blockers — "Talent Acquisition Data Lead" is an analytics role)
    "recruiter", "sourcer", "recruiting coordinator",
    "human resources", "people operations", "hr business partner",
    "benefits administrator",
    # finance & legal
    "financial analyst", "accountant", "accounting", "bookkeeper",
    "financial controller", "treasurer", "bookkeeping",
    "financial auditor", "internal auditor", "statutory auditor",
    "attorney", "counsel", "paralegal", "fp&a", "fpa",
    # support & ops  (must be the whole function, not a domain)
    "customer service associate", "customer support associate",
    "call center", "help desk associate",
    "fulfillment associate", "fulfilment associate", "warehouse associate",
    "warehouse picker", "delivery driver", "truck driver", "cab driver",
    "operations associate", "shift manager", "area manager",
    # facilities & physical
    "janitor", "custodian", "groundskeeper",
    "facilities manager", "facilities coordinator",
    "maintenance technician", "real estate", "construction manager",
    "electrician", "plumber", "hvac technician",
    # admin
    "administrative assistant", "executive assistant", "receptionist",
    "office manager", "office coordinator", "secretary",
    # procurement & supply
    "procurement specialist", "procurement manager",
    "merchandiser",
    # health & safety
    # NOT bare "safety specialist" — "Functional Safety Specialist (ISO 26262)"
    # is a mainstream Indian automotive/semiconductor engineering role.
    "nurse", "physician", "medical assistant", "ergonomist",
    "workplace safety", "occupational safety", "health specialist",
    # creative & education  (NOT bare "designer" — that kills the entire
    # VLSI/hardware-design category: RTL Designer, SoC Designer, Analog Designer)
    "graphic designer", "ux designer", "ui designer", "visual designer",
    "interior designer", "fashion designer", "web designer",
    "illustrator", "videographer", "photographer",
    "personal trainer", "fitness trainer", "yoga instructor",
    "teacher", "professor", "lecturer",
    # misc non-technical
    "librarian", "chef", "cook", "barista", "waiter",
    # senior non-technical leadership (no engineering word present)
    "vice president", "chief of staff", "general manager",
    "regional director", "country manager",
)

# Domain qualifiers: these describe the business area a role serves, not its
# function. They only reject when the title carries NO technical noun at all,
# so "Analytics Lead - Tax" and "GenAI Practice Lead, Compliance" survive while
# "Tax Manager" and "Compliance Officer" do not.
DOMAIN_QUALIFIERS = (
    "tax", "legal", "compliance", "regulatory", "revenue", "marketing",
    "payroll", "procurement", "facilities", "brand", "seo", "audit",
    "partnerships", "growth manager", "growth director", "compensation",
    "recruiting", "talent acquisition", "risk analyst", "underwriting",
    "claims", "category manager", "vendor manager", "merchandising", "buyer",
)

# Technical nouns that rescue a DOMAIN_QUALIFIER match. These are weaker than
# ENGINEERING_TERMS (they don't grant a pass on their own) but they show the
# role is technical: "Buyer Intelligence Lead", "Marketing Mix Modelling".
TECHNICAL_NOUNS = (
    "data", "dataset", "model", "modelling", "modeling", "intelligence",
    "knowledge graph", "classifier", "experimentation", "insight", "reporting",
    "dashboard", "etl", "pipeline", "automation", "engine", "api",
    "detection", "scoring", "fraud", "prediction", "forecast", "sentiment",
    "attribution", "graph", "embedding", "search", "relevance", "iot",
    "crawler", "signal", "segmentation", "ocr", "extraction", "matching",
    "entity", "technology", "triage", "recommendation",
)


def _normalize(title: str) -> str:
    """Lowercase and collapse punctuation to spaces, preserving word boundaries."""
    return " " + re.sub(r"[^\w+#]+", " ", title.lower()).strip() + " "


def _contains(haystack: str, phrase: str) -> bool:
    """Word-boundary containment. `phrase` may be multi-word."""
    needle = " " + re.sub(r"[^\w+#]+", " ", phrase.lower()).strip() + " "
    return needle in haystack


def _contains_inflected(haystack: str, phrase: str) -> bool:
    """Word-boundary containment tolerant of plural/gerund forms.

    "Solution Architects" must match "architect"; "Engineering" must match
    "engineer". Only applied to ENGINEERING_TERMS, where over-matching is safe
    (it grants a pass) — never to the blocklist, where it would over-reject.

    Suffixing is restricted to terms of length >= 5. Short abbreviations were
    generating junk matches: "ml"+"s" hit "MLS Realtor", "ai"+"s" hit "AIS
    Coordinator", "qa"+"s" hit "QAS Manager".
    """
    base = re.sub(r"[^\w+#]+", " ", phrase.lower()).strip()
    if _contains(haystack, base):
        return True
    if len(base) < 3:
        return False
    return any(_contains(haystack, base + suffix) for suffix in ("s", "ing"))


WEAK_TERMS = frozenset({"ai", "ml", "gen ai"})


def _engineering_terms(normalized: str) -> list[str]:
    """ALL matching engineering terms, not just the first.

    Returning only the first match was a bug: "ml"/"ai" sit early in the tuple,
    so "AI Evaluator Test Automation" reported `ai` and was treated as weak,
    even though `test` and `automation` were both present.
    """
    return [t for t in ENGINEERING_TERMS if _contains_inflected(normalized, t)]


def classify(title: str) -> tuple[str, str, str | None]:
    """Return (decision, reason_code, matched_term).

    Order matters:
      1. hard exclusion, unless a build-word shows it's the system being built
      2. engineering function word -> PASS (blocklist never consulted)
      3. non-engineering function blocklist -> REJECT
      4. domain qualifier with no technical noun -> REJECT
      5. otherwise PASS (ambiguous; the LLM stage decides)
    """
    if not title or not title.strip():
        return ("reject", "missing_title", None)

    n = _normalize(title)
    eng_all = _engineering_terms(n)
    has_build_word = any(_contains_inflected(n, w) for w in BUILD_WORDS)
    # A bare "ai"/"ml" token is too weak to rescue a hard exclusion ("AI
    # Evaluator" would survive on its own "ai"), but ANY other match is enough.
    strong_eng = any(t not in WEAK_TERMS for t in eng_all)

    for term in HARD_EXCLUSIONS:
        if _contains(n, term):
            # "Data Annotation Platform Engineer" builds the annotation system;
            # "Data Annotator" performs the annotation.
            if strong_eng or has_build_word:
                break
            return ("reject", "hard_exclusion", term)

    if eng_all:
        return ("pass", "engineering_function", eng_all[0])

    for term in BLOCKLIST:
        if _contains(n, term):
            return ("reject", "non_engineering_function", term)

    has_technical_noun = any(_contains_inflected(n, w) for w in TECHNICAL_NOUNS)
    if not has_technical_noun:
        for term in DOMAIN_QUALIFIERS:
            if _contains(n, term):
                return ("reject", "domain_qualifier_only", term)

    return ("pass", "ambiguous_no_function_word", None)


def passes(title: str) -> bool:
    return classify(title)[0] == "pass"
