#!/usr/bin/env bash
# Prompt v9 x reasoning-effort experiment on 500 frozen jobs from the 2026-10-04 batch.
#
#   bash experiments/llm_compare/run_v9_lab.sh        (from Git Bash, at the repo root)
#
# 1. Builds the 500-job set (deterministic): every job with your decision or a hand verdict,
#    plus random jobs where Luna and Sol agreed.
# 2. Smoke test: one job per configuration; stops before spending anything real if a
#    configuration is rejected or its replies do not validate.
# 3. Two lanes in parallel, each run resumable (rerunning skips calls already recorded):
#      Luna lane: v9 default x3, v9 high x3, v9 xhigh x3
#      Sol lane:  v9 xhigh x3, v9 default x2 (separates Sol's prompt effect from effort)
#    Output cap 16,000 tokens for every run so reasoning is never cut off.
# 4. Writes runs/2026-10-04/v9_summary.md: gate errors against your labels, show vs
#    uncertain tables, what would reach the report, and cost per run, next to the
#    existing prompt-1.3.0 default-effort runs (luna13, sol13).
# Expected: about $20 and 1-1.5 hours, longer if the gateway drops out (passes 2-3 retry).
# Not tied to midnight IST. Nothing here touches state/ or reads .env beyond the gateway
# settings the harness already uses.

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
LAB=$HERE/lab
D=$HERE/runs/2026-10-04
PASSES=3
PASS_WAIT=300
export LAB_BATCH=2026-10-04 PYTHONIOENCODING=utf-8

cd "$REPO" || exit 1
command -v uv > /dev/null || { echo "uv not found: run this from Git Bash, not WSL bash" >&2; exit 64; }
[ -f .env ] || { echo "missing $REPO/.env (gateway settings)" >&2; exit 64; }
[ -f "$LAB/cases_2026-10-04.json" ] || { echo "missing frozen cases for 2026-10-04" >&2; exit 64; }
LOG=$D/v9_lab.log
say() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

PROMPT=$D/prompt_v9.toml
cp "$LAB/prompts/v9.toml" "$PROMPT"   # freeze the exact prompt this run measures
say "prompt frozen at $PROMPT"
uv run --locked python "$LAB/effort_sets.py" | tee -a "$LOG" || { say "set build FAILED"; exit 1; }

# tag model effort reps
CONFIGS=(
    "v9_luna_default luna default 3"
    "v9_luna_high luna high 3"
    "v9_luna_xhigh luna xhigh 3"
    "v9_sol_xhigh sol xhigh 3"
    "v9_sol_default sol default 2"
)

run() {  # run TAG MODEL EFFORT REPS SET
    local tag=$1 model=$2 effort=$3 reps=$4 set=$5
    local extra=()
    [ "$effort" != default ] && extra=(--extra "{\"reasoning_effort\":\"$effort\"}")
    uv run --locked python "$LAB/lab.py" run --tag "$tag" --prompt "$PROMPT" --model "$model" \
        --set "$set" --reps "$reps" --workers 6 --max-output 16000 ${extra[@]+"${extra[@]}"} \
        >> "$D/$tag.log" 2>&1
}

say "smoke test: one job per configuration"
# Relative paths inside python -c: Git Bash converts /c/... only in arguments, not in code.
REL=experiments/llm_compare/lab
SMOKE_JOB=$(uv run --locked python -c "import json;print(json.load(open('$REL/sets_2026-10-04.json'))['effort500'][0])")
for config in "${CONFIGS[@]}"; do
    read -r tag model effort _ <<< "$config"
    run "smoke_$tag" "$model" "$effort" 1 "ords:$SMOKE_JOB"
    ok=$(uv run --locked python -c "
import json
rows = [json.loads(l) for l in open('$REL/results_2026-10-04/smoke_$tag.jsonl', encoding='utf-8')]
print(any(r['disposition'] == 'completed' for r in rows))")
    if [ "$ok" != True ]; then
        say "smoke test FAILED for $tag; see $D/smoke_$tag.log. Nothing else was run."
        exit 1
    fi
    say "smoke ok: $tag"
done

lane() {
    local config tag model effort reps pass
    for config in "$@"; do
        read -r tag model effort reps <<< "$config"
        for pass in $(seq 1 $PASSES); do
            say "$tag: pass $pass"
            run "$tag" "$model" "$effort" "$reps" effort500
            [ "$pass" -lt "$PASSES" ] && sleep $PASS_WAIT
        done
        say "$tag: done"
    done
}

say "runs: Luna lane and Sol lane in parallel"
( lane "${CONFIGS[0]}" "${CONFIGS[1]}" "${CONFIGS[2]}" ) &
luna_lane=$!
sleep 20
( lane "${CONFIGS[3]}" "${CONFIGS[4]}" ) &
sol_lane=$!
wait $luna_lane $sol_lane

S=$D/v9_summary.md
TAGS="luna13 sol13 v9_luna_default v9_luna_high v9_luna_xhigh v9_sol_default v9_sol_xhigh"
{
    echo "# Prompt v9 x reasoning effort, 500 jobs (2026-10-04 batch)"
    echo
    uv run --locked python "$LAB/score_v9.py" $TAGS
    echo
    echo "## Cost (harness calls at list prices; luna13/sol13 cover all 3,634 jobs)"
    echo '```'
    uv run --locked python "$LAB/costs.py" v9_luna_default:luna v9_luna_high:luna \
        v9_luna_xhigh:luna v9_sol_default:sol v9_sol_xhigh:sol
    echo '```'
} > "$S" 2>&1
say "all done; summary in $S"
