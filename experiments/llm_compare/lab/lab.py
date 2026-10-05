"""Prompt/model experiment harness over a frozen comparison batch. Never writes the repo DBs.

Run from the repository root with `uv run --locked python experiments/llm_compare/lab/lab.py`.

  build                      freeze cases.json from runs/2026-10-02 (git-ignored data)
  run   --tag T --prompt P --model M --set S [--reps N] [--workers W] [--extra JSON]
  score --tags T1,T2 [--set S] [--truth truth.json]

Results go to results/<tag>.jsonl, one line per (ordinal, rep) call; reruns of the same tag
skip calls already recorded, so an interrupted run resumes for free.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

from job_finder.core.search_profile import load_search_profile
from job_finder.daily_scan import NO_DESCRIPTION, _location
from job_finder.matching.evaluator import LLMProviderError, UsageBudget, UsageLimits
from job_finder.matching.merged_evaluator import MergedEvaluator
from job_finder.matching.merged_prompt import load_merged_prompt
from job_finder.matching.openai_client import (
    AmdGatewayClient,
    _gateway_client,
    load_gateway_settings,
)
from job_finder.persistence.batches import listing_from_payload

sys.path.insert(0, str(Path(__file__).resolve().parent))
import v2  # noqa: E402  (lab-only schema_version 2 contract)

HERE = Path(__file__).resolve().parent
# LAB_BATCH selects a comparison folder under runs/. The original 2026-10-02 batch keeps its
# unsuffixed file names; any other batch gets its own cases, sets and results.
BATCH_NAME = os.environ.get("LAB_BATCH", "2026-10-02")
_SUFFIX = "" if BATCH_NAME == "2026-10-02" else f"_{BATCH_NAME}"
BATCH = HERE.parent / "runs" / BATCH_NAME
CASES = HERE / f"cases{_SUFFIX}.json"
SETS = HERE / f"sets{_SUFFIX}.json"
RESULTS = HERE / f"results{_SUFFIX}"
PROFILES = {
    "luna": HERE.parent / "profiles" / "luna.env",
    "sol": HERE.parent / "profiles" / "sol.env",
}


def _env_file(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


# ---------------------------------------------------------------- build
def build() -> None:
    def results(name: str) -> dict[int, dict]:
        """Original CLI run results; absent for a discovery-only batch."""
        path = BATCH / name / "jobs.sqlite3"
        if not path.exists():
            return {}
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        return {o: json.loads(r) for o, r in c.execute(
            "select ordinal, result_json from batch_candidates") if r}

    luna, sol = results("luna"), results("sol")
    pristine = sqlite3.connect(f"file:{BATCH / 'pristine' / 'jobs.sqlite3'}?mode=ro", uri=True)
    profile = load_search_profile(Path("config/search_profile.toml"))
    cases = {}
    keys = dict(pristine.execute("select ordinal, job_key from batch_candidates"))
    for o, payload_json in pristine.execute("select ordinal, payload_json from batch_candidates"):
        row = listing_from_payload(json.loads(payload_json))
        if not row.normalized_job.description and BATCH_NAME == "2026-10-02":
            continue  # the original batch predates title-only judging; keep it unchanged
        cases[o] = {
            "ordinal": o,
            "job_key": keys[o],
            "company": row.company_id,
            "title": row.title_original,
            # Same placeholder production sends when a posting has no description.
            "description": row.normalized_job.description or NO_DESCRIPTION,
            "has_description": bool(row.normalized_job.description),
            "location_original": _location(row),
            "target": profile.seniority.description,
            "luna0": luna.get(o, {}),
            "sol0": sol.get(o, {}),
        }
    CASES.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    print(f"froze {len(cases)} cases -> {CASES}")


def load_cases() -> dict[int, dict]:
    return {int(k): v for k, v in json.loads(CASES.read_text(encoding="utf-8")).items()}


def load_set(name: str) -> list[int]:
    if name.startswith("ords:"):
        return [int(x) for x in name[5:].split(",")]
    return json.loads(SETS.read_text(encoding="utf-8"))[name]


# ---------------------------------------------------------------- run
class _Wire:
    """Inject extra create() kwargs and keep the finish_reason AmdGatewayClient discards."""

    def __init__(self, inner, extra: dict):
        self._inner, self._extra = inner, extra
        self.local = threading.local()
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        completion = self._inner.chat.completions.create(**kwargs, **self._extra)
        calls = getattr(self.local, "calls", None)
        if calls is not None:
            calls.append(completion.choices[0].finish_reason if completion.choices else None)
        return completion


def run(args) -> None:
    cases = load_cases()
    ordinals = load_set(args.set)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{args.tag}.jsonl"
    done = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r["disposition"] != "provider_error":
                done.add((r["ordinal"], r["rep"]))
    todo = [(o, rep) for rep in range(args.reps) for o in ordinals if (o, rep) not in done]
    print(f"{args.tag}: {len(todo)} calls to make ({len(done)} already recorded)", flush=True)

    if args.evidence_first:
        # Experiment: with structured output the model writes fields in schema order, so
        # put each judgment's evidence and reason BEFORE its verdict. Parsing is unchanged.
        import job_finder.matching.merged_evaluator as merged_module

        props = merged_module.MERGED_RESPONSE_SCHEMA["properties"]
        order = ["relevance_evidence", "relevance_reason", "relevance",
                 "seniority_evidence", "seniority_reason", "required_experience",
                 "detected_level", "seniority_match"]
        merged_module.MERGED_RESPONSE_SCHEMA = {
            **merged_module.MERGED_RESPONSE_SCHEMA,
            "properties": {k: props[k] for k in order},
            "required": order,
        }
        extras = merged_module._LOCATION_SCHEMA_EXTRAS
        merged_module._LOCATION_SCHEMA_EXTRAS = {
            k: extras[k] for k in ("location_evidence", "location_reason", "location_eligible")
        }

    env = {**os.environ, **_env_file(PROFILES[args.model]),
           "JOB_FINDER_LLM_MAX_OUTPUT_TOKENS_PER_REQUEST": str(args.max_output)}
    settings = load_gateway_settings(environment=env)
    wire = _Wire(_gateway_client(settings), json.loads(args.extra) if args.extra else {})
    gateway = AmdGatewayClient(settings, client=wire)
    # schema_version 2 prompts (v9 onwards) answer in a different shape; see v2.py.
    schema_version = v2.prompt_schema_version(Path(args.prompt))
    prompt = (v2.load_prompt if schema_version == 2 else load_merged_prompt)(Path(args.prompt))
    lock = threading.Lock()

    class _Tap:
        """Per-call usage capture around the shared gateway."""

        def __init__(self):
            self.responses = []

        def complete(self, request, policy):
            try:
                response = gateway.complete(request, policy)
            except LLMProviderError as error:
                if error.response is not None:
                    self.responses.append(error.response)
                raise
            self.responses.append(response)
            return response

    def one(o: int, rep: int) -> dict:
        case = cases[o]
        tap = _Tap()
        wire.local.calls = []
        evaluator = (v2.Evaluator if schema_version == 2 else MergedEvaluator)(
            client=tap, prompt=prompt, model_policy=settings.model_policy,
            budget=UsageBudget(UsageLimits(10**6, 10**12, 10**12, args.max_output)),
        )
        started = time.monotonic()
        for attempt in range(3):  # transport retries only; validation retry is the evaluator's
            try:
                outcome = evaluator.evaluate(
                    title=case["title"], description=case["description"],
                    target_description=case["target"],
                    location_original=case["location_original"],
                )
                disposition = outcome.disposition.value
                judgment = outcome.judgment
                if judgment is not None and not isinstance(judgment, dict):
                    judgment = asdict(judgment)
                errors = list(outcome.errors)
                break
            except LLMProviderError as error:
                disposition, judgment, errors = "provider_error", None, [str(error)]
                time.sleep(5 * (attempt + 1))
        # Keep raw replies: they are the only way to diagnose a rejected evidence quote.
        usage = [asdict(r) for r in tap.responses]
        return {
            "ordinal": o, "rep": rep, "schema": schema_version, "disposition": disposition,
            "judgment": judgment, "errors": errors, "finish": wire.local.calls,
            "usage": usage, "seconds": round(time.monotonic() - started, 1),
        }

    count = 0
    with ThreadPoolExecutor(args.workers) as pool, out.open("a", encoding="utf-8") as stream:
        futures = [pool.submit(one, o, rep) for o, rep in todo]
        for future in as_completed(futures):
            record = future.result()
            with lock:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
                count += 1
                if count % 50 == 0 or count == len(todo):
                    print(f"  {count}/{len(todo)}", flush=True)


# ---------------------------------------------------------------- score
def _revalidate(record: dict, case: dict) -> dict:
    """Re-judge a call with the *current* validator, as the evaluator would have.

    The evaluator keeps the first reply that validates. Runs made before a validator change
    recorded the old outcome; when raw replies were kept, replaying them makes old and new
    runs comparable.
    """
    from job_finder.matching.merged_prompt import MergedResponseError, parse_merged_response

    contents = [u.get("content") for u in record["usage"]]
    if not contents or any(c is None for c in contents):
        return record
    for content in contents:
        try:
            if record.get("schema") == 2:
                v2_judgment = v2.parse(
                    content, description=case["description"], title=case["title"],
                    location_original=case["location_original"],
                )
                return {**record, "disposition": "completed", "judgment": v2_judgment}
            judgment = parse_merged_response(
                content, description=case["description"], title=case["title"],
                location_requested=case["location_original"] is not None,
            )
        except MergedResponseError:
            continue
        # JSON round trip turns the str-enums into the plain values stored in results.
        return {**record, "disposition": "completed",
                "judgment": json.loads(json.dumps(asdict(judgment)))}
    if len(contents) < 2:
        # Newly invalid single reply: the evaluator would have retried, which we cannot
        # replay. Keep the recorded outcome rather than inventing a failure.
        return record
    return {**record, "disposition": "manual_review", "judgment": None}


def load_results(tag: str, revalidate: bool = True) -> dict[int, list[dict]]:
    cases = load_cases() if revalidate else {}
    by = collections.defaultdict(list)
    for line in (RESULTS / f"{tag}.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["disposition"] != "provider_error":
            by[r["ordinal"]].append(_revalidate(r, cases[r["ordinal"]]) if revalidate else r)
    return by


def vote(records: list[dict], field: str):
    values = [str(r["judgment"][field]) for r in records if r["judgment"]]
    if not values:
        return None, 0.0
    value, n = collections.Counter(values).most_common(1)[0]
    return value, n / len(values)


def visible(relevance: str | None, seniority: str | None) -> bool | None:
    """Would the job reach the report (match or review)? Location is never asked here."""
    if relevance is None:
        return None
    return relevance != "unrelated" and seniority != "False"


def score(args) -> None:
    cases = load_cases()
    truth = {}
    for path in (args.truth or "").split(","):
        if path:
            truth.update(json.loads(Path(path).read_text(encoding="utf-8")))
    allowed = {"low": {"low", "med", "high"}, "med": {"med", "high"}, "high": {"high"}}[
        args.min_conf
    ]
    truth = {int(k): v for k, v in truth.items() if v.get("conf", "high") in allowed}
    ordinals = load_set(args.set) if args.set else None
    for tag in args.tags.split(","):
        res = load_results(tag)
        keys = [o for o in (ordinals or res) if o in res]
        calls = [r for o in keys for r in res[o]]
        failed = sum(r["disposition"] != "completed" for r in calls)
        retried = sum(len(r["usage"]) > 1 for r in calls)
        outs = [u["output_tokens"] for r in calls for u in r["usage"]]
        ins = [u["input_tokens"] for r in calls for u in r["usage"]]
        print(f"\n== {tag}: {len(keys)} jobs, {len(calls)} calls, failed {failed}, "
              f"retried {retried}, mean in {sum(ins)/max(1,len(ins)):.0f} "
              f"out {sum(outs)/max(1,len(outs)):.0f}")
        for field in ("relevance", "seniority_match"):
            unstable = sum(vote(res[o], field)[1] < 1 for o in keys)
            line = f"  {field:16s} unstable across reps: {unstable}/{len(keys)}"
            for ref in ("sol0", "luna0"):
                pairs = [(vote(res[o], field)[0], str(cases[o][ref]["judgment"][field]))
                         for o in keys if cases[o][ref].get("judgment")]
                line += f" | vs {ref}: {sum(a == b for a, b in pairs)}/{len(pairs)}"
            if truth:
                pairs = [(vote(res[o], field)[0], str(truth[o][field]))
                         for o in keys if o in truth and field in truth[o]]
                line += f" | vs truth: {sum(a == b for a, b in pairs)}/{len(pairs)}"
            print(line)
        if truth:
            # Relevance gate: does the job pass "not unrelated"? Independent of seniority.
            gate_fn, gate_fp, gate_n, gate_missed = 0, 0, 0, []
            for o in keys:
                if o not in truth or "relevance" not in truth[o]:
                    continue
                gate_n += 1
                t = truth[o]["relevance"] != "unrelated"
                p = vote(res[o], "relevance")[0] not in (None, "unrelated")
                if t and not p:
                    gate_fn += 1
                    gate_missed.append(o)
                elif p and not t:
                    gate_fp += 1
            print(f"  relevance gate vs truth on {gate_n}: missed {gate_fn}, extra {gate_fp}"
                  f" | missed: {gate_missed}")
            # Production makes ONE call per job; the vote above flatters that. Average the
            # per-call gate errors over every recorded call instead.
            single_fn = single_fp = single_n = 0
            for o in keys:
                if o not in truth or "relevance" not in truth[o]:
                    continue
                t = truth[o]["relevance"] != "unrelated"
                for r in res[o]:
                    if not r["judgment"]:
                        single_fn += t  # a failed call shows nothing
                        single_n += 1
                        continue
                    p = r["judgment"]["relevance"] != "unrelated"
                    single_n += 1
                    single_fn += t and not p
                    single_fp += p and not t
            if single_n:
                print(f"  single-call gate: missed {single_fn / single_n * gate_n:.1f}, "
                      f"extra {single_fp / single_n * gate_n:.1f} (expected per {gate_n} jobs)")
            fn = fp = n = 0
            misses = []
            for o in keys:
                if o not in truth or "relevance" not in truth[o]:
                    continue
                n += 1
                t = visible(truth[o]["relevance"], str(truth[o].get("seniority_match")))
                p = visible(vote(res[o], "relevance")[0], vote(res[o], "seniority_match")[0])
                if t and not p:
                    fn += 1
                    misses.append(o)
                elif p and not t:
                    fp += 1
            print(f"  visibility vs truth on {n}: missed {fn} (worse), extra {fp} | missed: {misses}")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    r = sub.add_parser("run")
    r.add_argument("--tag", required=True)
    r.add_argument("--prompt", default="config/merged_prompt.toml")
    r.add_argument("--model", choices=sorted(PROFILES), default="luna")
    r.add_argument("--set", required=True)
    r.add_argument("--reps", type=int, default=1)
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--max-output", type=int, default=2000)
    r.add_argument("--extra", help='extra create() kwargs as JSON, e.g. {"reasoning_effort":"low"}')
    r.add_argument("--evidence-first", action="store_true",
                   help="schema asks for evidence and reason before each verdict")
    s = sub.add_parser("score")
    s.add_argument("--tags", required=True)
    s.add_argument("--set")
    s.add_argument("--truth", help="comma-separated truth files")
    s.add_argument("--min-conf", choices=("low", "med", "high"), default="med")
    args = p.parse_args()
    {"build": lambda a: build(), "run": run, "score": score}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
