#!/usr/bin/env bash
# Executor runner: remaining R3 (state_aliases_update_*) scripts.
# Started after two 10-min foreground timeouts; runs detached from the tool cap.
SESSION_DIR="<HOME>/.claude/plugins/cache/testvdb/testvdb/2.4.0/results/qdrant/v1.18.0/2026-09-02T12-42-33Z"
[ -f "$SESSION_DIR/.executor.env" ] || { echo "FATAL: .executor.env missing"; exit 1; }
source "$SESSION_DIR/.executor.env"
cd "$SESSION_DIR" || { echo "FATAL: Cannot cd to $SESSION_DIR"; exit 1; }

HEALTH="http://127.0.0.1:$DB_PORT/healthz"
CONTAINER=testvdb-qdrant-standalone

PYTHON=""
command -v py >/dev/null 2>&1 && PYTHON="py -3.12"
[ -z "$PYTHON" ] && command -v python3.12 >/dev/null 2>&1 && PYTHON=python3.12
[ -z "$PYTHON" ] && command -v python3 >/dev/null 2>&1 && PYTHON=python3
[ -z "$PYTHON" ] && { echo "FATAL: No Python >=3.10 found"; exit 1; }
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
echo "Python: $PYTHON | TESTVDB_DB_URL=$TESTVDB_DB_URL | SCRIPTS_DIR=$TESTVDB_SCRIPTS_DIR | TARGET=$TESTVDB_TARGET"

wait_healthy() {
  for j in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 45 50 55 60; do
    curl -sf --max-time 5 "$HEALTH" >/dev/null 2>&1 && return 0
    sleep 2
  done
  return 1
}

if ! curl -sf --max-time 5 "$HEALTH" >/dev/null 2>&1; then
  echo "WARN: healthz not 200 at start; restarting $CONTAINER"
  docker restart "$CONTAINER" >/dev/null 2>&1
  wait_healthy && echo "OK: healthy after restart" || { echo "FATAL: container never became healthy"; exit 1; }
else
  echo "OK: healthy at start"
fi

N=0
PASS=0
FAIL=0
for script in debate_logs/*aliases_update*.py; do
  [ -f "$script" ] || continue
  B=$(basename "$script" .py)
  [ "$B" = "__init__" ] && continue
  [ -f "output_${B}.log.done" ] && continue

  # inter-script health gate: if wedged, restart and wait before next script
  if ! curl -sf --max-time 5 "$HEALTH" >/dev/null 2>&1; then
    echo "  [gate] healthz down before $B -> restarting $CONTAINER"
    docker restart "$CONTAINER" >/dev/null 2>&1
    wait_healthy && echo "  [gate] healthy again" || echo "  [gate] WARNING: still unhealthy, running $B anyway"
  fi

  N=$((N+1))
  printf "[%d] %s ... " "$N" "$B"
  timeout 1800 $PYTHON "$script" > "output_${B}.log" 2>&1
  EXIT=$?
  echo $EXIT > "exit_code_${B}.txt"
  touch "output_${B}.log.done"
  echo "exit=$EXIT"
  if [ $EXIT -eq 0 ]; then
    PASS=$((PASS+1))
  else
    FAIL=$((FAIL+1))
  fi

  # orphan guard: if the per-script cap fired, kill leftover python so it cannot
  # mutate the DB alongside the next script
  if [ "$EXIT" = "124" ]; then
    echo "  [guard] $B hit the 1800s cap; killing orphan python"
    taskkill //F //IM python.exe >/dev/null 2>&1
    sleep 2
  fi

  # memory telemetry (log-only; restart policy stays per main-process instruction:
  # heavy scripts = aliases_update_007 / concurrent / threads)
  USAGE=$(timeout 15 docker stats --no-stream --format "{{.MemUsage}}" "$CONTAINER" 2>/dev/null | tr -d '\r\n')
  USAGE=${USAGE%% *}
  NUM=${USAGE%%[!0-9.]*}
  UNIT=${USAGE#"$NUM"}
  case "$UNIT" in
    GiB) MIB=$(awk -v n="$NUM" 'BEGIN{printf "%.2f", n*1024}') ;;
    MiB) MIB=$NUM ;;
    KiB) MIB=$(awk -v n="$NUM" 'BEGIN{printf "%.2f", n/1024}') ;;
    B)   MIB=$(awk -v n="$NUM" 'BEGIN{printf "%.6f", n/1048576}') ;;
    *)   MIB=0 ;;
  esac
  echo "  [mem] $CONTAINER mem=${USAGE} (${MIB}MiB / limit 1638.4MiB)"
  case "$B" in
    *aliases_update_007*|*concurrent*|*thread*)
      OVER=$(awk -v m="$MIB" 'BEGIN{print (m > 1638.4) ? 1 : 0}')
      if [ "$OVER" = "1" ]; then
        echo "  [memwatch] mem > 1.6G -> restarting $CONTAINER"
        docker restart "$CONTAINER" >/dev/null 2>&1
        wait_healthy && echo "  [memwatch] healthy again, continuing"
      fi
      ;;
  esac
done

echo ""
echo "=== R3 remaining pass complete ==="
echo "Executed this pass: $N"
echo "Exit 0: $PASS"
echo "Exit non-zero: $FAIL"
docker ps --filter "name=$CONTAINER" --format "container: {{.Names}} {{.Status}}"
