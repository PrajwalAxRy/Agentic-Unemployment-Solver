#!/usr/bin/env bash
# Reasoning-effort comparison on the 1,000 labelled jobs: Luna default vs high vs xhigh,
# for prompts 1.3.0, 1.4.0 and v10, with 3 calls per job at every effort.
#
#   bash experiments/llm_compare/run_effort_2026-10-05.sh      (Git Bash, repo root)
#
# Reuses the benchmark's frozen prompts and its default (x3) and xhigh (x2) results:
# adds high x3 for each prompt and tops xhigh up to 3 calls per job, so every effort is
# compared on the same number of calls. Resumable; smoke test first.
# Writes runs/2026-10-05/effort_summary.md. Expected: about $5 and 1-1.5 hours.

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
for p in 1.3.0 1.4.0 v10; do
    [ -f "$D/prompt_$p.toml" ] || { echo "missing $D/prompt_$p.toml: run run_bench_2026-10-05.sh first" >&2; exit 64; }
done
LOG=$D/effort.log
say() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

# tag prompt effort reps
HIGH_LANE=(
    "b130_luna_high 1.3.0 high 3"
    "b140_luna_high 1.4.0 high 3"
    "b10_luna_high v10 high 3"
)
XHIGH_LANE=(
    "b130_luna_xhigh 1.3.0 xhigh 3"
    "b140_luna_xhigh 1.4.0 xhigh 3"
    "b10_luna_xhigh v10 xhigh 3"
)

run() {  # run TAG PROMPT EFFORT REPS SET
    uv run --locked python "$LAB/lab.py" run --tag "$1" --prompt "$D/prompt_$2.toml" \
        --model luna --set "$5" --reps "$4" --workers 6 --max-output 16000 \
        --extra "{\"reasoning_effort\":\"$3\"}" >> "$D/$1.log" 2>&1
}

REL=experiments/llm_compare/lab
SMOKE_JOB=$(uv run --locked python -c "import json;print(json.load(open('$REL/sets_2026-10-05.json'))['bench1000'][0])")
for config in "${HIGH_LANE[@]}"; do
    read -r tag prompt effort _ <<< "$config"
    run "smoke_$tag" "$prompt" "$effort" 1 "ords:$SMOKE_JOB"
    ok=$(uv run --locked python -c "
import json
rows = [json.loads(l) for l in open('$REL/results_2026-10-05/smoke_$tag.jsonl', encoding='utf-8')]
print(any(r['disposition'] == 'completed' for r in rows))")
    [ "$ok" = True ] || { say "smoke test FAILED for $tag; see $D/smoke_$tag.log"; exit 1; }
    say "smoke ok: $tag"
done

lane() {
    local config tag prompt effort reps pass
    for config in "$@"; do
        read -r tag prompt effort reps <<< "$config"
        for pass in $(seq 1 $PASSES); do
            say "$tag: pass $pass"
            run "$tag" "$prompt" "$effort" "$reps" bench1000
            [ "$pass" -lt "$PASSES" ] && sleep $PASS_WAIT
        done
        say "$tag: done"
    done
}

say "runs: high and xhigh lanes in parallel"
( lane "${HIGH_LANE[@]}" ) &
a=$!
sleep 20
( lane "${XHIGH_LANE[@]}" ) &
b=$!
wait $a $b

S=$D/effort_summary.md
{
    echo "# Luna reasoning effort: default vs high vs xhigh, 3 calls per job (2026-10-05 batch)"
    echo
    echo "Truth: policy v1.2 labels after the re-check. 'per call' = expected errors with one"
    echo "call per job, as in production. Lower is better everywhere."
    uv run --locked python "$LAB/score_bench.py" \
        b130_luna_default b130_luna_high b130_luna_xhigh \
        b140_luna_default b140_luna_high b140_luna_xhigh \
        b10_luna_default b10_luna_high b10_luna_xhigh
    echo
    echo "## Cost and latency (harness calls at list prices)"
    echo '```'
    uv run --locked python "$LAB/costs.py" \
        b130_luna_default:luna b130_luna_high:luna b130_luna_xhigh:luna \
        b140_luna_default:luna b140_luna_high:luna b140_luna_xhigh:luna \
        b10_luna_default:luna b10_luna_high:luna b10_luna_xhigh:luna
    echo '```'
} > "$S" 2>&1
say "all done; summary in $S"
