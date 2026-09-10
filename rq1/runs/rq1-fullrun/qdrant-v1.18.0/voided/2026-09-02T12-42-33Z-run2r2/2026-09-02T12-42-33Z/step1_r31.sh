set -u
SESSION_DIR="<HOME>/.claude/plugins/cache/testvdb/testvdb/2.4.0/results/qdrant/v1.18.0/2026-09-02T12-42-33Z"
[ -d "$SESSION_DIR" ] || { echo "FATAL: Session directory not found: $SESSION_DIR"; exit 1; }
cd "$SESSION_DIR" || { echo "FATAL: cannot cd to SESSION_DIR"; exit 1; }

# --- Step 0 verify / repair .executor.env ---
if [ ! -f .executor.env ]; then
  printf '%s\n' \
    'export TARGET=qdrant' \
    'export DB_PORT=6333' \
    'export HEALTH_PATH=/healthz' \
    "export SESSION_DIR=$SESSION_DIR" \
    'export TESTVDB_DB_URL=http://127.0.0.1:6333' \
    'export TESTVDB_TARGET=qdrant' \
    'export TESTVDB_SCRIPTS_DIR=<HOME>/.claude/plugins/cache/testvdb/testvdb/2.4.0/scripts' > .executor.env
  echo "NOTE: .executor.env was missing; created with qdrant/6333"
fi
grep -q '^export TESTVDB_TARGET=' .executor.env || echo 'export TESTVDB_TARGET=qdrant' >> .executor.env
grep -q '^export TESTVDB_SCRIPTS_DIR=' .executor.env || echo 'export TESTVDB_SCRIPTS_DIR=<HOME>/.claude/plugins/cache/testvdb/testvdb/2.4.0/scripts' >> .executor.env
sed -i 's|^export TESTVDB_DB_URL=.*|export TESTVDB_DB_URL=http://127.0.0.1:6333|' .executor.env
sed -i 's|^export HEALTH_PATH=.*|export HEALTH_PATH=/healthz|' .executor.env
source .executor.env
echo "VERIFY: TARGET=$TARGET DB_PORT=$DB_PORT HEALTH_PATH=$HEALTH_PATH"
echo "VERIFY: TESTVDB_DB_URL=$TESTVDB_DB_URL TESTVDB_TARGET=$TESTVDB_TARGET"
echo "VERIFY: TESTVDB_SCRIPTS_DIR=$TESTVDB_SCRIPTS_DIR"
[ "$TARGET" = "qdrant" ] && [ "$DB_PORT" = "6333" ] || { echo "FATAL: .executor.env mismatch (expected qdrant/6333)"; exit 1; }

# --- persist PYTHON choice for later turns ---
PYTHON=""
command -v py >/dev/null 2>&1 && PYTHON="py -3.12"
[ -z "$PYTHON" ] && command -v python3.12 >/dev/null 2>&1 && PYTHON="python3.12"
[ -z "$PYTHON" ] && command -v python3 >/dev/null 2>&1 && PYTHON="python3"
[ -z "$PYTHON" ] && { echo "FATAL: no Python >=3.10 found"; exit 1; }
grep -q '^export PYTHON_CMD=' .executor.env || echo "export PYTHON_CMD=$PYTHON" >> .executor.env
source .executor.env
echo "Python: $PYTHON_CMD"
command -v timeout >/dev/null 2>&1 && echo "timeout: available" || echo "timeout: MISSING (will run bare)"

# --- stale executor pre-check ---
echo "=== Stale executor pre-check ==="
N_STALE=$(powershell -NoProfile -Command '@(Get-CimInstance Win32_Process | Where-Object { ($_.Name -like "py*") -and ($_.CommandLine -match "state_percol") }).Count' 2>/dev/null | tr -d '\r')
echo "Running py* processes matching state_percol: ${N_STALE:-unknown}"
[ "${N_STALE:-0}" = "0" ] || { echo "FATAL: stale executor loop detected - aborting to avoid double-run"; exit 1; }
ls output_state_percol_*.log exit_code_state_percol_*.txt 2>/dev/null || echo "No stale state_percol outputs from earlier attempts"

# --- R31 script enumeration (filenames only; content not read) ---
echo "=== R31 scripts under debate_logs/ ==="
echo "Count: $(ls debate_logs/state_percol_*.py 2>/dev/null | wc -l)"
for f in debate_logs/state_percol_*.py; do [ -f "$f" ] && basename "$f"; done

# --- Step 1: container ensure + health ---
echo "=== Container check ==="
docker ps >/dev/null 2>&1 || { echo "FATAL: docker daemon not reachable"; exit 1; }
RUNNING=$(docker ps --filter "name=testvdb-qdrant" --format "{{.Names}}")
echo "Running containers matching testvdb-qdrant: ${RUNNING:-none}"
if [ -z "$RUNNING" ]; then
  docker start testvdb-qdrant-standalone 2>&1 || echo "ERROR: docker start testvdb-qdrant-standalone failed"
fi
HEALTHY=0
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -sf --noproxy "*" "http://127.0.0.1:6333/healthz" --max-time 5 >/dev/null 2>&1; then HEALTHY=1; break; fi
  echo "Waiting ($i/10)..."; sleep 2
done
[ "$HEALTHY" = "1" ] && echo "OK: qdrant healthy at http://127.0.0.1:6333/healthz" || { echo "FATAL: qdrant not healthy after 10 retries"; exit 1; }
docker ps --filter "name=testvdb-qdrant" --format "{{.Names}} | {{.Status}} | {{.Image}}"
echo "STEP1-DONE"
