"""Price harness runs from their recorded usage, at the list prices in profiles/<model>.env.

  LAB_BATCH=2026-10-05 python costs.py luna13:luna sol13:sol luna13_sen:luna

Harness calls never reach the SQLite spending ledger, so this is their only cost record.
Every recorded call is priced, including validation retries and failed attempts.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402

from job_finder.cost import TokenRates  # noqa: E402


def rates(model: str) -> TokenRates:
    env = lab._env_file(lab.PROFILES[model])
    return TokenRates(
        input_per_mtok=float(env["JOB_FINDER_LLM_INPUT_COST_PER_MTOK"]),
        output_per_mtok=float(env["JOB_FINDER_LLM_OUTPUT_COST_PER_MTOK"]),
        cached_input_per_mtok=float(env["JOB_FINDER_LLM_CACHED_INPUT_COST_PER_MTOK"]),
        cache_write_per_mtok=float(env["JOB_FINDER_LLM_CACHE_WRITE_COST_PER_MTOK"]),
    )


for spec in sys.argv[1:]:
    tag, model = spec.split(":")
    price = rates(model)
    path = lab.RESULTS / f"{tag}.jsonl"
    if not path.exists():
        print(f"{tag:14s} no results")
        continue
    total = 0.0
    calls = jobs = 0
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        seen.add(record["ordinal"])
        for usage in record["usage"]:
            calls += 1
            total += price.input_cost_of(
                usage["input_tokens"],
                cached_tokens=usage.get("cached_input_tokens") or 0,
                cache_write_tokens=usage.get("cache_write_tokens") or 0,
            ) + usage["output_tokens"] * price.output_per_mtok / 1_000_000
    jobs = len(seen)
    print(f"{tag:14s} model={model} jobs={jobs} calls={calls} "
          f"cost=USD {total:.2f} per_call={total / max(1, calls):.5f}")
