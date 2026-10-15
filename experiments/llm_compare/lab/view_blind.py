"""Print cases WITHOUT any model answers, for blind adjudication.

LAB_BATCH=2026-10-03 python view_blind.py 12,34,56
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402

cases = lab.load_cases()
for o in (int(x) for x in sys.argv[1].split(",")):
    c = cases[o]
    print(f"\n######## #{o} [{c['company']}] {c['title']} | location: {c['location_original']}")
    print("  " + " ".join(c["description"].split()))
