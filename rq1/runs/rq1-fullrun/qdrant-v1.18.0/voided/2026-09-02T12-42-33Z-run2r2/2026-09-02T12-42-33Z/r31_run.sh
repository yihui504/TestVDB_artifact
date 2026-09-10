set -u
SESSION_DIR="<HOME>/.claude/plugins/cache/testvdb/testvdb/2.4.0/results/qdrant/v1.18.0/2026-09-02T12-42-33Z"
cd "$SESSION_DIR" || { echo "FATAL: cannot cd to SESSION_DIR"; exit 1; }
[ -f .executor.env ] || { echo "FATAL: .executor.env missing"; exit 1; }
source .executor.env
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
export NO_PROXY="127.0.0.1,localhost${NO_PROXY:+,$NO_PROXY}"
export no_proxy="$NO_PROXY"

B="${1:?usage: r31_run.sh <script_basename> [heavy]}"
MODE="${2:-light}"
SCRIPT="$SESSION_DIR/debate_logs/${B}.py"
[ -f "$SCRIPT" ] || { echo "FATAL: missing $SCRIPT"; exit 1; }
echo "PY=$PYTHON_CMD DB=$TESTVDB_DB_URL"

echo "RUN $B mode=$MODE start $(date '+%H:%M:%S')"
if command -v timeout >/dev/null 2>&1; then
  timeout -k 10 595 $PYTHON_CMD "$SCRIPT" > "$SESSION_DIR/output_${B}.log" 2>&1
else
  $PYTHON_CMD "$SCRIPT" > "$SESSION_DIR/output_${B}.log" 2>&1
fi
EXIT=$?
echo "$EXIT" > "$SESSION_DIR/exit_code_${B}.txt"
touch "$SESSION_DIR/output_${B}.log.done"
echo "$B exit=$EXIT end $(date '+%H:%M:%S')"

if [ "$MODE" = "heavy" ]; then
  echo "--- docker stats after $B ---"
  docker stats --no-stream testvdb-qdrant-standalone
fi
