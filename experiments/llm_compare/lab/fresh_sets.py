"""Case sets for a fresh batch: everything, and the postings not seen in 2026-10-02.

LAB_BATCH=2026-10-03 uv run --locked python experiments/llm_compare/lab/fresh_sets.py
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402

old_db = lab.HERE.parent / "runs" / "2026-10-02" / "pristine" / "jobs.sqlite3"
old_keys = {
    key
    for (key,) in sqlite3.connect(f"file:{old_db.as_posix()}?mode=ro", uri=True).execute(
        "select job_key from batch_candidates"
    )
}
cases = lab.load_cases()
sets = {
    "all": sorted(cases),
    "new": sorted(o for o, c in cases.items() if c["job_key"] not in old_keys),
    "no_description": sorted(o for o, c in cases.items() if not c.get("has_description", True)),
}
lab.SETS.write_text(json.dumps(sets))
print({name: len(ordinals) for name, ordinals in sets.items()})
