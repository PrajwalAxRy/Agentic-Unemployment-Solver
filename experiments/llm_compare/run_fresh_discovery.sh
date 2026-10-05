#!/usr/bin/env bash
# Fresh batch for the unbiased benchmark: discovery only, no LLM calls, no model cost.
#
#   bash experiments/llm_compare/run_fresh_discovery.sh     (Git Bash, from the repo root)
#
# 1. job-finder scan --discovery-only (~3 hours): collects, filters and saves full
#    descriptions into state/jobs.sqlite3 (the dev database; this replaces its saved batch).
# 2. Copies that database to runs/<IST date>/pristine/jobs.sqlite3 and marks it read-only:
#    the frozen input every benchmark run reads.
# 3. Freezes the batch into lab/cases_<IST date>.json for labelling and the harness.
# Run it any time of day; it makes no model calls, so midnight IST does not matter.

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
DATE=$(date -u -d '+330 minutes' +%F)
D=$HERE/runs/$DATE

cd "$REPO" || exit 1
command -v uv > /dev/null || { echo "uv not found: run this from Git Bash, not WSL bash" >&2; exit 64; }
[ -f .env ] || { echo "missing $REPO/.env (scan loads its settings even without LLM calls)" >&2; exit 64; }
if [ -e "$D/pristine/jobs.sqlite3" ]; then
    echo "$D already holds a frozen batch; move it aside or run on another IST day" >&2
    exit 64
fi
mkdir -p "$D/pristine"
LOG=$D/fresh_discovery.log
say() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

say "discovery: starting (about 3 hours); output in $D/discovery.log"
uv run --locked job-finder scan --discovery-only --plain \
    --min-request-interval 0.15 --max-concurrent-per-host 2 > "$D/discovery.log" 2>&1
code=$?
if [ $code -ne 0 ] && [ $code -ne 2 ]; then
    say "discovery: FAILED exit=$code; see $D/discovery.log"
    exit 1
fi
say "discovery: done exit=$code (2 = some sources failed; healthy sources still form the batch)"

uv run --locked job-finder state backup --output "$D/pristine/jobs.sqlite3" >> "$LOG" 2>&1 \
    || { say "snapshot FAILED"; exit 1; }
attrib +R "$(cygpath -w "$D/pristine/jobs.sqlite3")" > /dev/null
{ git rev-parse HEAD; git status --short; } > "$D/code_version.txt"
say "snapshot: $D/pristine/jobs.sqlite3 (read-only)"

LAB_BATCH=$DATE PYTHONIOENCODING=utf-8 uv run --locked python "$HERE/lab/lab.py" build >> "$LOG" 2>&1 \
    || { say "freezing cases FAILED"; exit 1; }
say "cases frozen for LAB_BATCH=$DATE; all done"
tail -3 "$D/discovery.log" | tee -a "$LOG"
