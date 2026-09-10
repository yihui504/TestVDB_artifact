#!/usr/bin/env bash
# R10 batch runner -- collections_create round (qdrant v1.18.0, session qdrant-1180-r2r)
# Executes ONLY this round's scripts: *collections_create*.py under debate_logs/
set -u
SESSION_DIR="<HOME>/.claude/plugins/cache/testvdb/testvdb/2.4.0/results/qdrant/v1.18.0/2026-09-02T12-42-33Z"
cd "$SESSION_DIR" || { echo "FATAL: cannot cd to $SESSION_DIR"; exit 1; }
[ -f .executor.env ] || { echo "FATAL: .executor.env missing"; exit 1; }
source .executor.env

PYTHON=""
command -v py >/dev/null 2>&1 && PYTHON="py -3.12"
[ -z "$PYTHON" ] && command -v python3.12 >/dev/null 2>&1 && PYTHON=python3.12
[ -z "$PYTHON" ] && command -v python3 >/dev/null 2>&1 && PYTHON=python3
[ -z "$PYTHON" ] && { echo "FATAL: No Python >=3.10 found"; exit 1; }
echo "Python: $PYTHON"
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

HEALTH="http://127.0.0.1:6333/healthz"
ORDER="execution_order_r10.txt"
STALL="health_events_r10.log"
LIST=".r10_scripts.txt"
: > "$ORDER"; : > "$STALL"

# Discover this round's R10 scripts only (R1-R9 scripts are NOT touched)
find "$SESSION_DIR/debate_logs" -type f -name "*collections_create*.py" | sort > "$LIST"
N_DISCOVERED=$(grep -c '\.py$' "$LIST")
echo "Discovered $N_DISCOVERED R10 scripts (*collections_create*.py under debate_logs/)"
[ "$N_DISCOVERED" -gt 0 ] || { echo "FATAL: no R10 scripts found"; exit 1; }

# Per-script cap to guard against a hung script (threads in state_collections_create_014)
if command -v timeout >/dev/null 2>&1; then
  PER_SCRIPT="timeout 300"
else
  PER_SCRIPT=""
  echo "NOTE: 'timeout' not available; running without per-script cap"
fi

N=0; PASS=0; FAIL=0
while read -r script; do
  [ -f "$script" ] || continue
  REL=${script#"$SESSION_DIR/debate_logs/"}
  B=${REL%.py}
  B=${B//\//__}
  N=$((N+1))
  printf '[%d] %s %s\n' "$N" "$(date '+%H:%M:%S')" "$REL" >> "$ORDER"
  printf '[%d] %s ... ' "$N" "$B"
  # preserve pre-existing artifacts for this basename (rerun safety)
  if [ -f "output_${B}.log.done" ]; then
    mv -f "output_${B}.log" "output_${B}.log.prev_r10" 2>/dev/null
    mv -f "exit_code_${B}.txt" "exit_code_${B}.txt.prev_r10" 2>/dev/null
    rm -f "output_${B}.log.done"
  fi
  $PER_SCRIPT $PYTHON "$script" > "output_${B}.log" 2>&1
  EXIT=$?
  echo "$EXIT" > "exit_code_${B}.txt"
  touch "output_${B}.log.done"
  if [ $EXIT -eq 0 ]; then PASS=$((PASS+1)); echo "exit=0"; else FAIL=$((FAIL+1)); echo "exit=$EXIT"; fi
  # health watch: record any post-script unhealthy state for stall attribution
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH" --max-time 5)
  if [ "$CODE" != "200" ]; then
    echo "$(date '+%H:%M:%S') after #$N $B healthz=$CODE" >> "$STALL"
  fi
done < "$LIST"

echo ""
echo "=== Execution Complete (R10 collections_create) ==="
echo "Total executed: $N (discovered: $N_DISCOVERED)"
echo "Exit 0: $PASS"
echo "Exit non-zero: $FAIL"

CODE=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH" --max-time 5)
echo "post-batch healthz: HTTP $CODE"
if [ "$CODE" != "200" ]; then
  echo "container unhealthy after batch; 30s recheck before restart decision"
  sleep 30
  CODE2=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH" --max-time 5)
  echo "recheck healthz: HTTP $CODE2"
  if [ "$CODE2" != "200" ]; then
    echo "RESTARTING testvdb-qdrant-standalone"
    docker restart testvdb-qdrant-standalone
    for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
      sleep 2
      C=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH" --max-time 5)
      if [ "$C" = "200" ]; then echo "healthy again after restart (attempt $i)"; break; fi
    done
  fi
fi

if [ -s "$STALL" ]; then
  echo "--- health events during batch (scripts after first stall are rerun candidates) ---"
  cat "$STALL"
else
  echo "no health events during batch"
fi
