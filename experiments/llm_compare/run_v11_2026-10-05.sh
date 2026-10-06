#!/usr/bin/env bash
# Prompt v11 (v10 + the "testing WITH AI is not testing AI" clarification) vs v10, both on
# Luna high effort, 3 calls per job, on the 1,000 labelled jobs of the 2026-10-05 batch.
#
#   bash experiments/llm_compare/run_v11_2026-10-05.sh      (Git Bash, repo root)
#
# Reuses the existing v10 high results (b10_luna_high); runs only v11. Resumable; smoke test
# first. Writes runs/2026-10-05/v11_summary.md. Expected: about $1.20 and 30-45 minutes.

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
LAB=$HERE/lab
D=$HERE/runs/2026-10-05
PASSES=3
PASS_WAIT=300
TAG=b11_luna_high
export LAB_BATCH=2026-10-05 PYTHONIOENCODING=utf-8

cd "$REPO" || exit 1
command -v uv > /dev/null || { echo "uv not found: run this from Git Bash, not WSL bash" >&2; exit 64; }
[ -f .env ] || { echo "missing $REPO/.env (gateway settings)" >&2; exit 64; }
[ -f "$LAB/results_2026-10-05/b10_luna_high.jsonl" ] || { echo "missing v10 high results: run run_effort_2026-10-05.sh first" >&2; exit 64; }
LOG=$D/v11.log
say() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

cp "$LAB/prompts/v11.toml" "$D/prompt_v11.toml"
say "prompt frozen at $D/prompt_v11.toml"

run() {  # run TAG REPS SET
    uv run --locked python "$LAB/lab.py" run --tag "$1" --prompt "$D/prompt_v11.toml" \
        --model luna --set "$3" --reps "$2" --workers 6 --max-output 16000 \
        --extra '{"reasoning_effort":"high"}' >> "$D/$1.log" 2>&1
}

REL=experiments/llm_compare/lab
SMOKE_JOB=$(uv run --locked python -c "import json;print(json.load(open('$REL/sets_2026-10-05.json'))['bench1000'][0])")
run "smoke_$TAG" 1 "ords:$SMOKE_JOB"
ok=$(uv run --locked python -c "
import json
rows = [json.loads(l) for l in open('$REL/results_2026-10-05/smoke_$TAG.jsonl', encoding='utf-8')]
print(any(r['disposition'] == 'completed' for r in rows))")
[ "$ok" = True ] || { say "smoke test FAILED; see $D/smoke_$TAG.log"; exit 1; }
say "smoke ok"

for pass in $(seq 1 $PASSES); do
    say "$TAG: pass $pass"
    run "$TAG" 3 bench1000
    [ "$pass" -lt "$PASSES" ] && sleep $PASS_WAIT
done

S=$D/v11_summary.md
{
    echo "# Prompt v11 vs v10, Luna high effort, 3 calls per job (2026-10-05 batch)"
    echo
    echo "Truth: policy v1.2 labels after the re-check. Lower is better everywhere."
    uv run --locked python "$LAB/score_bench.py" b10_luna_high b11_luna_high
    echo
    echo '```'
    uv run --locked python "$LAB/costs.py" b10_luna_high:luna b11_luna_high:luna
    echo '```'
} > "$S" 2>&1
say "all done; summary in $S"
