#!/bin/sh
# TestVDB R11 executor runner (resumable, attempts-capped, DB-health-gated).
# Executes ONLY this round's 23 scripts.
# - skips scripts that already completed with a non-124 exit
# - re-runs prior guard-kills (124) up to MAXATTEMPTS
# - before each script: ensures healthz=200, recovering the container
#   (docker start/restart + wait) if it went down (known: memory-limit panics
#   under resource-heavy collections_create legs)
# - invokes python.exe directly so the timeout guard cannot orphan it
SESSION_DIR="<HOME>/.claude/plugins/cache/testvdb/testvdb/2.4.0/results/qdrant/v1.18.0/2026-09-02T12-42-33Z"
cd "$SESSION_DIR" || { echo "FATAL: cannot cd" >> r11_progress.log; exit 1; }
. "$SESSION_DIR/.executor.env"
export TESTVDB_DB_URL TESTVDB_TARGET TESTVDB_SCRIPTS_DIR
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1
PYTHON="<HOME>/AppData/Local/Programs/Python/Python312/python.exe"
GUARD=480
MAXATTEMPTS=2
CONTAINER=testvdb-qdrant-standalone

ensure_db() {
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:6333/healthz 2>/dev/null)
  [ "$CODE" = "200" ] && return 0
  echo "$(date +%H:%M:%S) DB_DOWN healthz=$CODE -> recovering $CONTAINER" >> r11_progress.log
  ST=$(docker inspect "$CONTAINER" --format '{{.State.Status}}' 2>/dev/null)
  if [ "$ST" = "running" ]; then
    docker restart "$CONTAINER" >> r11_progress.log 2>&1
  else
    docker start "$CONTAINER" >> r11_progress.log 2>&1
  fi
  for j in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do
    CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:6333/healthz 2>/dev/null)
    [ "$CODE" = "200" ] && { echo "$(date +%H:%M:%S) DB_RECOVERED healthz=200" >> r11_progress.log; return 0; }
    sleep 3
  done
  echo "$(date +%H:%M:%S) DB_UNRECOVERABLE healthz=$CODE" >> r11_progress.log
  return 1
}

# healthz poller: self-limiting (1920 x 15s = 8h max) so a killed runner cannot leak it forever
( I=0
  while [ $I -lt 1920 ]; do
    echo "$(date +%H:%M:%S) healthz=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:6333/healthz 2>/dev/null)"
    sleep 15
    I=$((I+1))
  done ) >> healthz_poll_r11.log 2>&1 &
POLLER=$!

for B in \
  boundary_collections_create_013 boundary_collections_create_014 boundary_collections_create_015 \
  boundary_collections_create_016 boundary_collections_create_017 boundary_collections_create_018 \
  boundary_collections_create_019 \
  state_collections_create_015 state_collections_create_016 state_collections_create_017 \
  state_collections_create_018 state_collections_create_019 state_collections_create_020 \
  state_collections_create_021 \
  semantic_collections_create_016 semantic_collections_create_017 semantic_collections_create_018 \
  semantic_collections_create_019 semantic_collections_create_020 semantic_collections_create_021 \
  semantic_collections_create_022 semantic_collections_create_023 semantic_collections_create_024
do
  SCRIPT="debate_logs/$B.py"
  if [ ! -f "$SCRIPT" ]; then
    echo "$(date +%H:%M:%S) $B MISSING_FILE" >> r11_progress.log
    continue
  fi
  ATT=0
  [ -f "r11_att_$B" ] && ATT=$(cat "r11_att_$B" 2>/dev/null)
  if [ "$ATT" -ge "$MAXATTEMPTS" ]; then
    echo "$(date +%H:%M:%S) $B SKIP(attempts=$ATT cap reached)" >> r11_progress.log
    continue
  fi
  if [ -f "exit_code_${B}.txt" ]; then
    PRIOR=$(cat "exit_code_${B}.txt" 2>/dev/null)
    if [ "$PRIOR" != "124" ]; then
      echo "$(date +%H:%M:%S) $B SKIP(completed exit=$PRIOR)" >> r11_progress.log
      continue
    fi
  fi
  if ! ensure_db; then
    echo "$(date +%H:%M:%S) ABORT_RUNNER before $B (DB unrecoverable)" >> r11_progress.log
    break
  fi
  ATT=$((ATT+1))
  echo "$ATT" > "r11_att_$B"
  echo "$(date +%H:%M:%S) $B START attempt=$ATT" >> r11_progress.log
  S=$(date +%s)
  timeout $GUARD $PYTHON "$SCRIPT" > "output_${B}.log" 2>&1
  EXIT=$?
  E=$(( $(date +%s) - S ))
  echo "$EXIT" > "exit_code_${B}.txt"
  touch "output_${B}.log.done"
  HZ=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:6333/healthz 2>/dev/null)
  echo "$(date +%H:%M:%S) $B exit=$EXIT ${E}s healthz=$HZ" >> r11_progress.log
done

kill "$POLLER" 2>/dev/null
echo "RUNNER_DONE $(date +%H:%M:%S)" >> r11_progress.log
