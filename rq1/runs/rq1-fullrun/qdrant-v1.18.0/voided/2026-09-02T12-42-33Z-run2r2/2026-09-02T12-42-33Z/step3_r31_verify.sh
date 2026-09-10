set -u
SESSION_DIR="<HOME>/.claude/plugins/cache/testvdb/testvdb/2.4.0/results/qdrant/v1.18.0/2026-09-02T12-42-33Z"
cd "$SESSION_DIR" || { echo "FATAL: cannot cd to SESSION_DIR"; exit 1; }
[ -f .executor.env ] && source .executor.env

echo "=== Verification ==="
echo "Done files: $(ls output_state_percol_*.log.done 2>/dev/null | wc -l)"
echo "Log files:  $(ls output_state_percol_*.log 2>/dev/null | wc -l)"
echo "Exit codes: $(ls exit_code_state_percol_*.txt 2>/dev/null | wc -l)"

echo ""
echo "=== Exit codes (all 8, numeric order) ==="
for B in state_percol_create_queryable_001 state_percol_delete_gone_002 state_percol_count_consistency_003 state_percol_count_concurrent_004 state_percol_point_delete_gone_005 state_percol_point_delete_concurrent_006 state_percol_payload_overwrite_007 state_percol_index_toggle_008; do
  if [ -f "exit_code_${B}.txt" ]; then
    echo "  $B: exit=$(cat "exit_code_${B}.txt")"
  else
    echo "  $B: MISSING exit code file"
  fi
done

echo ""
echo "=== Log sizes ==="
ls -lh output_state_percol_*.log 2>/dev/null | awk '{print $5, $NF}'

echo ""
echo "=== Container state (left running for Reporter) ==="
docker ps --filter "name=testvdb-qdrant" --format "{{.Names}} | {{.Status}} | {{.Image}}"
echo "STEP3-DONE"
