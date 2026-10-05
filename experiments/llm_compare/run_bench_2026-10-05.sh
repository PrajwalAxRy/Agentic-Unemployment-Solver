#!/usr/bin/env bash
# Fresh benchmark: prompts 1.3.0 (production) vs 1.4.0 vs v10 on the 1,000 labelled jobs of
# the 2026-10-05 batch, scored against policy v1.2 truth (lab/truth_bench_2026-10-05.json).
#
#   bash experiments/llm_compare/run_bench_2026-10-05.sh             (Git Bash, repo root)
#   WITH_SOL=1 bash experiments/llm_compare/run_bench_2026-10-05.sh  (also Sol, 1 call/job)
#
# 1. Freezes the three prompts next to the results so the run measures exactly them.
# 2. Smoke test: one job per configuration; stops before spending anything real if a
#    configuration is rejected or its replies do not validate.
# 3. Runs, resumable (rerunning skips calls already recorded), two lanes in parallel:
#      default lane: 1.3.0, 1.4.0, v10 at Luna default effort, 3 calls per job
#      xhigh lane:   1.3.0, 1.4.0, v10 at Luna xhigh effort, 2 calls per job
#      (WITH_SOL=1)  1.4.0 and v10 on Sol default, 1 call per job, in a third lane
#    Output cap 16,000 tokens everywhere so reasoning is never cut off.
# 4. Writes runs/2026-10-05/bench_summary.md: per half, missed and extra jobs (relevance
#    alone and end to end), seniority errors, instability, the soft tier table for the
#    tuning half, and cost. The sealed test half shows counts only.
# Expected: about $6-8 for Luna (+$8 with Sol) and 2-3 hours. Not tied to midnight IST.
# Nothing here touches state/; the gateway settings are read the same way as earlier runs.

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
LAB=$HERE/lab
D=$HERE/runs/2026-10-05
PASSES=3
PASS_WAIT=300
export LAB_BATCH=2026-10-05 PYTHONIOENCODING=utf-8

cd "$REPO" || exit 1
command -v uv > /dev/null || { echo "uv not found: run this from Git Bash, not WSL bash" >&2; exit 64; }
[ -f .env ] || { echo "missing $REPO/.env (gateway settings)" >&2; exit 64; }
[ -f "$LAB/cases_2026-10-05.json" ] || { echo "missing frozen cases for 2026-10-05" >&2; exit 64; }
[ -f "$LAB/truth_bench_2026-10-05.json" ] || { echo "missing benchmark truth" >&2; exit 64; }
mkdir -p "$D"
LOG=$D/bench.log
say() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

cp "$REPO/config/merged_prompt.toml" "$D/prompt_1.3.0.toml"
cp "$LAB/prompts/p140.toml" "$D/prompt_1.4.0.toml"
cp "$LAB/prompts/v10.toml" "$D/prompt_v10.toml"
say "prompts frozen in $D"

# tag prompt model effort reps
DEFAULT_LANE=(
    "b130_luna_default 1.3.0 luna default 3"
    "b140_luna_default 1.4.0 luna default 3"
    "b10_luna_default v10 luna default 3"
)
XHIGH_LANE=(
    "b130_luna_xhigh 1.3.0 luna xhigh 2"
    "b140_luna_xhigh 1.4.0 luna xhigh 2"
    "b10_luna_xhigh v10 luna xhigh 2"
)
SOL_LANE=(
    "b140_sol_default 1.4.0 sol default 1"
    "b10_sol_default v10 sol default 1"
)
CONFIGS=("${DEFAULT_LANE[@]}" "${XHIGH_LANE[@]}")
[ "${WITH_SOL:-0}" = 1 ] && CONFIGS+=("${SOL_LANE[@]}")

run() {  # run TAG PROMPT MODEL EFFORT REPS SET
    local tag=$1 prompt=$2 model=$3 effort=$4 reps=$5 set=$6
    local extra=()
    [ "$effort" != default ] && extra=(--extra "{\"reasoning_effort\":\"$effort\"}")
    uv run --locked python "$LAB/lab.py" run --tag "$tag" --prompt "$D/prompt_$prompt.toml" \
        --model "$model" --set "$set" --reps "$reps" --workers 6 --max-output 16000 \
        ${extra[@]+"${extra[@]}"} >> "$D/$tag.log" 2>&1
}

say "smoke test: one job per configuration"
# Relative paths inside python -c: Git Bash converts /c/... only in arguments, not in code.
REL=experiments/llm_compare/lab
SMOKE_JOB=$(uv run --locked python -c "import json;print(json.load(open('$REL/sets_2026-10-05.json'))['bench1000'][0])")
for config in "${CONFIGS[@]}"; do
    read -r tag prompt model effort _ <<< "$config"
    run "smoke_$tag" "$prompt" "$model" "$effort" 1 "ords:$SMOKE_JOB"
    ok=$(uv run --locked python -c "
import json
rows = [json.loads(l) for l in open('$REL/results_2026-10-05/smoke_$tag.jsonl', encoding='utf-8')]
print(any(r['disposition'] == 'completed' for r in rows))")
    if [ "$ok" != True ]; then
        say "smoke test FAILED for $tag; see $D/smoke_$tag.log. Nothing else was run."
        exit 1
    fi
    say "smoke ok: $tag"
done

lane() {
    local config tag prompt model effort reps pass
    for config in "$@"; do
        read -r tag prompt model effort reps <<< "$config"
        for pass in $(seq 1 $PASSES); do
            say "$tag: pass $pass"
            run "$tag" "$prompt" "$model" "$effort" "$reps" bench1000
            [ "$pass" -lt "$PASSES" ] && sleep $PASS_WAIT
        done
        say "$tag: done"
    done
}

say "runs: default and xhigh lanes in parallel${WITH_SOL:+, plus Sol}"
( lane "${DEFAULT_LANE[@]}" ) &
lanes=($!)
sleep 20
( lane "${XHIGH_LANE[@]}" ) &
lanes+=($!)
if [ "${WITH_SOL:-0}" = 1 ]; then
    sleep 20
    ( lane "${SOL_LANE[@]}" ) &
    lanes+=($!)
fi
wait "${lanes[@]}"

TAGS="b130_luna_default b140_luna_default b10_luna_default b130_luna_xhigh b140_luna_xhigh b10_luna_xhigh"
COSTS="b130_luna_default:luna b140_luna_default:luna b10_luna_default:luna b130_luna_xhigh:luna b140_luna_xhigh:luna b10_luna_xhigh:luna"
if [ "${WITH_SOL:-0}" = 1 ]; then
    TAGS="$TAGS b140_sol_default b10_sol_default"
    COSTS="$COSTS b140_sol_default:sol b10_sol_default:sol"
fi
S=$D/bench_summary.md
{
    echo "# Benchmark: prompts 1.3.0 / 1.4.0 / v10 on 1,000 labelled jobs (2026-10-05 batch)"
    echo
    echo "Truth: policy v1.2 labels. 'per call' = expected errors with one call per job, as in"
    echo "production; 'vote' = majority over the run's calls. Lower is better everywhere."
    uv run --locked python "$LAB/score_bench.py" $TAGS
    echo
    echo "## Cost (harness calls at list prices)"
    echo '```'
    uv run --locked python "$LAB/costs.py" $COSTS
    echo '```'
} > "$S" 2>&1
say "all done; summary in $S"
