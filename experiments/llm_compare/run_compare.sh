#!/usr/bin/env bash
# Unattended Luna vs Sol comparison: discovery -> snapshots -> both evaluations -> costs.
#
#   bash experiments/llm_compare/run_compare.sh                  # full run
#   bash experiments/llm_compare/run_compare.sh --skip-discovery # reuse today's batch
#   bash experiments/llm_compare/run_compare.sh --models luna    # one model only
#   bash experiments/llm_compare/run_compare.sh --resume 2026-10-02
#       finish an interrupted comparison folder with `evaluate` (same IST day only),
#       using the profiles saved in that folder so prices cannot drift mid-comparison.
#
# Each model runs on its own database copy with its own lock, in parallel, so both start
# well before midnight IST. A run halted by a gateway failure (exit 6) is resumed with
# `evaluate` automatically; evaluate refuses after midnight IST, which ends the retries.
# Per-model settings come from profiles/<model>.env, exported on top of JOB_Finder/.env,
# so .env itself is never copied or modified. Run folders (databases, logs, reports) go to
# runs/<IST date>/, which is git-ignored.

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
PROFILES=$HERE/profiles
ROOT=${COMPARE_ROOT:-$HERE/runs}  # override only for testing
MAX_RESUMES=10
RESUME_WAIT_SECONDS=180

skip_discovery=false
resume_date=
models=(luna sol)
while [ $# -gt 0 ]; do
    case $1 in
        --skip-discovery) skip_discovery=true ;;
        --resume) shift; resume_date=$1 ;;
        --models) shift; IFS=, read -r -a models <<< "$1" ;;
        *) echo "unknown option: $1" >&2; exit 64 ;;
    esac
    shift
done

cd "$REPO" || exit 1

if [ -n "$resume_date" ]; then
    D=$ROOT/$resume_date
    [ -d "$D" ] || { echo "no comparison folder $D" >&2; exit 64; }
    PROFILES=$D  # the copies saved when the comparison started
else
    # The batch's admission date is the IST date when discovery *starts*.
    D=$ROOT/$(date -u -d '+330 minutes' +%F)
fi
for m in "${models[@]}"; do
    [ -f "$PROFILES/$m.env" ] || { echo "missing $PROFILES/$m.env" >&2; exit 64; }
done
mkdir -p "$D"
SUMMARY=$D/summary.txt
say() { echo "$(date '+%F %T') $*" | tee -a "$SUMMARY"; }

if [ -n "$resume_date" ]; then
    say "resume: finishing ${models[*]} in $D with evaluate"
elif ! $skip_discovery; then
    say "discovery: starting (takes ~3.5h); output in $D/discovery.log"
    uv run --locked job-finder scan --discovery-only --plain \
        --min-request-interval 0.15 --max-concurrent-per-host 2 > "$D/discovery.log" 2>&1
    code=$?
    if [ $code -ne 0 ] && [ $code -ne 2 ]; then
        say "discovery: FAILED exit=$code; see $D/discovery.log"
        exit 1
    fi
    say "discovery: done exit=$code"
fi

first_command=evaluate
if [ -z "$resume_date" ]; then
    first_command=force_reevaluate
    say "snapshots: pristine ${models[*]}"
    for d in pristine "${models[@]}"; do
        mkdir -p "$D/$d"
        if [ -e "$D/$d/jobs.sqlite3" ]; then
            say "snapshots: $D/$d/jobs.sqlite3 already exists; refusing to overwrite"
            exit 1
        fi
        uv run --locked job-finder state backup --output "$D/$d/jobs.sqlite3" \
            >> "$SUMMARY" 2>&1 || { say "snapshots: backup for $d FAILED"; exit 1; }
    done
    attrib +R "$(cygpath -w "$D/pristine/jobs.sqlite3")" > /dev/null
    { git rev-parse HEAD; git status --short; } > "$D/code_version.txt"
    cp "$PROFILES"/*.env "$D/"
else
    # The code changed since the comparison started; keep both versions on record.
    { echo "--- resumed $(date '+%F %T')"; git rev-parse HEAD; git status --short; } \
        >> "$D/code_version.txt"
fi

run_model() {
    local m=$1 dir=$D/$1 command=$first_command code attempt
    mkdir -p "$dir/reports"
    # Subshell-local export: the profile overrides .env for this model only.
    set -a; . "$PROFILES/$m.env"; set +a
    for attempt in $(seq 0 $MAX_RESUMES); do
        say "$m: $command (attempt $attempt)"
        uv run --locked job-finder --log-directory "$dir" "$command" --plain \
            --database "$dir/jobs.sqlite3" --lock "$dir/scan.lock" \
            --cost-ledger "$dir/llm_costs.jsonl" \
            --json-output "$dir/reports/latest_scan.json" \
            --markdown-output "$dir/reports/latest_scan.md" >> "$dir/console.log" 2>&1
        code=$?
        case $code in
            0|2) say "$m: finished exit=$code"; break ;;
            6) say "$m: halted with pending jobs; resuming in ${RESUME_WAIT_SECONDS}s"
               command=evaluate; sleep $RESUME_WAIT_SECONDS ;;
            *) say "$m: stopped exit=$code (after midnight IST, or a fatal error); see $dir/console.log"
               break ;;
        esac
    done
    uv run --locked job-finder costs --database "$dir/jobs.sqlite3" \
        --ledger "$dir/llm_costs.jsonl" > "$dir/costs.txt" 2>&1
}

pids=()
for m in "${models[@]}"; do
    ( run_model "$m" ) &
    pids+=($!)
    sleep 30  # stagger the starts so both don't hit the gateway at the same instant
done
wait "${pids[@]}"

say "results:"
for m in "${models[@]}"; do
    uv run --locked python - "$D/$m/jobs.sqlite3" "$m" >> "$SUMMARY" 2>&1 <<'EOF'
import sqlite3, sys
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
total, done = c.execute(
    "SELECT COUNT(*), COUNT(result_json) FROM batch_candidates").fetchone()
counts = dict(c.execute(
    "SELECT json_extract(result_json, '$.disposition'), COUNT(*) FROM batch_candidates "
    "WHERE result_json IS NOT NULL GROUP BY 1").fetchall())
print(f"  {sys.argv[2]}: {done}/{total} judged {counts}")
EOF
    sed -n '/^usage model=/,$p' "$D/$m/costs.txt" | sed 's/^/  /' >> "$SUMMARY"
done
say "all done; summary in $SUMMARY"
