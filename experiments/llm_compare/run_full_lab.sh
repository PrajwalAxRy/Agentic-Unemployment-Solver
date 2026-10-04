#!/usr/bin/env bash
# One-command lab run: fresh discovery, Luna through the real pipeline, and harness reruns.
#
#   bash experiments/llm_compare/run_full_lab.sh
#
# 1. run_compare.sh --models luna: discovery (~3.5h) into runs/<IST date>/, a read-only
#    "pristine" snapshot, then Luna 1.3.0 through force_reevaluate on its own database copy
#    with the second opinion on (profiles/luna.env). Checks the real code path: review
#    list, matches, costs, request caps.
# 2. As soon as the snapshot exists, three harness runs over the frozen batch, in parallel
#    with step 1 and with each other. They keep every raw answer:
#      luna13      Luna, prompt 1.3.0, 4 calls per job   (~$4.5)
#      sol13       Sol,  prompt 1.3.0, 3 calls per job   (~$42)
#      luna13_sen  Luna, seniority variant v8s, 2 calls  (~$2.2)
# 3. A summary in runs/<date>/lab_summary.txt.
#
# Start by ~14:00 IST: the pipeline step must start before midnight IST (and can only
# resume before it). The harness runs are not tied to midnight; if they are interrupted,
# rerunning the same lab.py command resumes them for free (see lab_<tag>.log).
# Nothing here reads or prints .env; per-model settings come from profiles/*.env.

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
LAB=$HERE/lab
DATE=$(date -u -d '+330 minutes' +%F)
D=$HERE/runs/$DATE
PASSES=3            # harness passes per tag; later passes only redo provider errors
PASS_WAIT=300       # seconds between passes, to ride out a gateway outage

cd "$REPO" || exit 1

hour=$(date -u -d '+330 minutes' +%-H)
if [ "$hour" -ge 19 ] && [ "${FORCE_LATE:-}" != 1 ]; then
    echo "It is ${hour}:xx IST. Discovery takes ~3.5h and the pipeline step must start" >&2
    echo "before midnight IST. Start earlier, or set FORCE_LATE=1 to run anyway (the" >&2
    echo "harness runs would still work; the pipeline step would likely be refused)." >&2
    exit 64
fi
[ -f .env ] || { echo "missing $REPO/.env (gateway settings)" >&2; exit 64; }
if [ -e "$D/pristine/jobs.sqlite3" ]; then
    echo "$D already holds a batch; move it aside or wait for the next IST day" >&2
    exit 64
fi
mkdir -p "$D"
LOG=$D/full_lab.log
say() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

say "full lab run in $D"
say "step 1: discovery + Luna pipeline (run_compare.sh --models luna); see $D/summary.txt"
bash "$HERE/run_compare.sh" --models luna > "$D/run_compare.out" 2>&1 &
compare_pid=$!

# run_compare.sh logs "luna: force_reevaluate (attempt 0)" right after the snapshots.
until grep -q "luna: force_reevaluate" "$D/summary.txt" 2>/dev/null; do
    if ! kill -0 "$compare_pid" 2>/dev/null; then
        say "step 1 ended before the snapshot existed; see $D/summary.txt and discovery.log"
        exit 1
    fi
    sleep 60
done
say "snapshot ready; freezing the batch for the harness"

# Freeze the exact prompt and code used, so later edits cannot change what was measured.
cp config/merged_prompt.toml "$D/prompt_1.3.0.toml"
cp "$LAB/prompts/v8s.toml" "$D/prompt_v8s.toml"
export LAB_BATCH=$DATE PYTHONIOENCODING=utf-8
uv run --locked python "$LAB/lab.py" build >> "$LOG" 2>&1 || { say "build FAILED"; exit 1; }
uv run --locked python "$LAB/fresh_sets.py" >> "$LOG" 2>&1 || { say "sets FAILED"; exit 1; }

harness() {
    local tag=$1 pass
    shift
    for pass in $(seq 1 $PASSES); do
        say "$tag: pass $pass"
        uv run --locked python "$LAB/lab.py" run --tag "$tag" --set all "$@" \
            >> "$D/lab_$tag.log" 2>&1
        [ "$pass" -lt "$PASSES" ] && sleep $PASS_WAIT
    done
    say "$tag: done"
}

say "step 2: harness runs (logs: $D/lab_<tag>.log)"
( harness luna13 --prompt "$D/prompt_1.3.0.toml" --model luna --reps 4 --workers 6 ) &
p1=$!
sleep 20
( harness sol13 --prompt "$D/prompt_1.3.0.toml" --model sol --reps 3 --workers 6 ) &
p2=$!
sleep 20
( harness luna13_sen --prompt "$D/prompt_v8s.toml" --model luna --reps 2 --workers 4 ) &
p3=$!
wait $p1 $p2 $p3
say "harness runs finished; waiting for the pipeline step"
wait "$compare_pid"
say "pipeline step finished"

say "step 3: summary -> $D/lab_summary.txt"
S=$D/lab_summary.txt
{
    echo "== cost (harness calls, list prices)"
    uv run --locked python "$LAB/costs.py" luna13:luna sol13:sol luna13_sen:luna
    echo
    echo "== stability and agreement (votes over reps)"
    uv run --locked python "$LAB/lab.py" score --tags luna13,sol13,luna13_sen --set all
    echo
    echo "== shown jobs (relevant and seniority not false), first answer per tag"
    uv run --locked python "$LAB/compare_full.py" sol13,luna13,luna13_sen
    echo
    echo "== pipeline step (Luna 1.3.0 + second opinion)"
    cat "$D/summary.txt"
} > "$S" 2>&1
say "all done; summary in $S"
