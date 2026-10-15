"""Print one chunk of benchmark jobs for blind labelling (no model answers anywhere).

  LAB_BATCH=2026-10-05 python label_chunk.py N        # chunk N (0-based), 20 jobs each
  LAB_BATCH=2026-10-05 python label_chunk.py status   # how many labelled so far

Order is a seeded shuffle of bench1000, so hard and random jobs are interleaved.
Labels go to labels_2026-10-05.txt, one line per job:
  ordinal | relevance | seniority | location | confidence | reason
relevance: core / involved / uncertain / hide; seniority: yes / no / uncertain;
location: - (not asked) or india / open_remote / relocation / excluded / uncertain;
confidence 1-10 as defined in policy/policy_v1.md section 7.
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402

SIZE = 20
LABELS = lab.HERE / f"labels_{lab.BATCH_NAME}.txt"
order = lab.load_set("bench1000")
random.Random(7).shuffle(order)


def labelled() -> set[int]:
    if not LABELS.exists():
        return set()
    return {
        int(line.split("|")[0])
        for line in LABELS.read_text("utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


if sys.argv[1] == "status":
    done = labelled()
    missing = [i // SIZE for i, o in enumerate(order) if o not in done]
    print(f"labelled {len(done)} of {len(order)}; next chunk {missing[0] if missing else '-'}")
    sys.exit()

import re  # noqa: E402

# Display-only trimming. Closing boilerplate is cut from the first marker found in the last
# 45% of a posting; Barclays' level-expectations block (identical on every posting of a
# level) is replaced by its level name. Duties and requirements precede these markers.
TAIL_MARKERS = re.compile(
    r"(equal (employment )?opportunit|is proud to be an equal|we celebrate diversity|"
    r"our inclusive culture|reasonable accommodation|privacy notice|"
    r"recruitment fraud|about adobe|why join us\?|benefits & perks|our commitment|"
    r"what's in it for you|unleash your potential|we offer a competitive|"
    r"culture and total rewards|corporate security responsibility)",
    re.I,
)
BARCLAYS = re.compile(
    r"(Analyst|Assistant Vice President|Vice President|Director) Expectations .*?"
    r"how we behave\.",
    re.S,
)


def trim(text: str) -> str:
    text = BARCLAYS.sub(lambda m: f"[Barclays {m.group(1)} expectations template]", text)
    start = int(len(text) * 0.55)
    match = TAIL_MARKERS.search(text, start)
    if match:
        text = text[: match.start()] + f"[... {len(text) - match.start()} chars of boilerplate]"
    return text


cases = lab.load_cases()
n = int(sys.argv[1])
for o in order[n * SIZE : (n + 1) * SIZE]:
    c = cases[o]
    loc = c["location_original"]
    print(
        f"\n######## {o} | [{c['company']}] {c['title']}"
        + (f" | LOCATION ASKED: {loc}" if loc is not None else "")
    )
    print("  " + trim(" ".join(c["description"].split())))
