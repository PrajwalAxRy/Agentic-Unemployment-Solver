"""Run the merged call on real location-review rows, which never reached the model before.

Takes the deterministic location reviews saved in a batch's metadata (descriptions were not
kept for them), fetches their descriptions through the normal adapters, and asks Luna (x3)
and Sol (x1) the full merged question including location. Results go to
lab/location_probe_<batch>.json.

  uv run --locked python experiments/llm_compare/lab/location_probe.py [batch]
"""

import json
import os
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy
from job_finder.cli import _runtime_adapters
from job_finder.core.company_registry import load_company_registry
from job_finder.core.search_profile import load_search_profile
from job_finder.matching.evaluator import LLMProviderError, UsageBudget, UsageLimits
from job_finder.matching.merged_evaluator import MergedEvaluator
from job_finder.matching.merged_prompt import load_merged_prompt
from job_finder.matching.openai_client import AmdGatewayClient, load_gateway_settings
from job_finder.persistence.batches import listing_from_payload
from job_finder.scan import _ensure_description

HERE = Path(__file__).resolve().parent
batch = sys.argv[1] if len(sys.argv) > 1 else "2026-10-02"
db = HERE.parent / "runs" / batch / "pristine" / "jobs.sqlite3"
metadata = json.loads(
    sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    .execute("select metadata_json from daily_batch")
    .fetchone()[0]
)
rows = [
    listing_from_payload(r)
    for r in metadata["filtered"]["reviews"]
    if r["company_id"] != "bank-of-america"  # fixed separately: these now resolve and reject
]
print(f"{len(rows)} location-review rows")

registry = load_company_registry(Path("config/company_sources.json"))
sources = {e.source.company_id: e.source for e in registry.entries}
profile = load_search_profile(Path("config/search_profile.toml"))
adapters = _runtime_adapters(BoundedHttpClient(policy=HttpPolicy(timeout_seconds=20)))
prompt = load_merged_prompt(Path("config/merged_prompt.toml"))


def evaluator(model: str) -> MergedEvaluator:
    env = dict(os.environ)
    for line in (HERE.parent / "profiles" / f"{model}.env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    settings = load_gateway_settings(environment=env)
    return MergedEvaluator(
        client=AmdGatewayClient(settings),
        prompt=prompt,
        model_policy=settings.model_policy,
        budget=UsageBudget(UsageLimits(10**6, 10**12, 10**12, 2000)),
    )


luna, sol = evaluator("luna"), evaluator("sol")
out = []
for row in rows:
    detailed, _, error = _ensure_description(
        row.normalized_job, sources[row.company_id], adapters, profile
    )
    job = detailed or row.normalized_job
    description = job.description or "The source published no job description for this posting."
    calls = {}
    for name, model, reps in (("luna", luna, 3), ("sol", sol, 1)):
        calls[name] = []
        for _ in range(reps):
            try:
                outcome = model.evaluate(
                    title=row.title_original,
                    description=description,
                    target_description=profile.seniority.description,
                    location_original=row.location_original,
                )
                calls[name].append(
                    asdict(outcome.judgment) if outcome.judgment else outcome.disposition.value
                )
            except LLMProviderError as exc:
                calls[name].append(f"provider_error: {exc}")
    out.append(
        {
            "company": row.company_id,
            "title": row.title_original,
            "location_original": row.location_original,
            "filter_reason": row.location.reason_code if row.location else None,
            "description_error": error,
            "description": description,
            "calls": calls,
        }
    )
    summary = {
        k: [
            c["relevance"] + "/" + str(c["location_eligible"]) if isinstance(c, dict) else c
            for c in v
        ]
        for k, v in calls.items()
    }
    print(
        f"{row.company_id:16s} {row.title_original[:40]:40s} {row.location_original[:28]:28s} "
        f"{summary}",
        flush=True,
    )

(HERE / f"location_probe_{batch}.json").write_text(
    json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8"
)
