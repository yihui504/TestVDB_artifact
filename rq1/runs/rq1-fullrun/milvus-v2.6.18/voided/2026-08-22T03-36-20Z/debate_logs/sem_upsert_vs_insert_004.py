# script_id: sem_upsert_vs_insert_004
# Attack: semantic strategy upsert vs insert equivalence on existing pk (visibility + pk handling matrix)
"""
Matrix: for autoID=false collection with existing row pk=5:
 - insert same pk=5 again -> rejected (duplicate pk) OR silently deduped; record which
 - upsert pk=5 -> code 0, count unchanged, get returns new vector (upsert equivalence semantics)
Defect signals: insert duplicate pk code 0 AND count grows to 2 AND get id=5 returns ambiguous rows;
upsert count drift; 500s.
"""
import sys, time
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.18\2026-08-22T03-36-20Z\debate_logs")
from _milvus_helper import safe_request, code, drop, wait_flush, row_count

CL = "sem_upsert_ins_004"
VERDICT = "SCRIPT_ERROR"
try:
    drop(CL)
    s, b, raw = safe_request("POST", "collections+create", {"collectionName": CL, "dimension": 4, "autoID": False, "idType": "Int64"})
    print("create:", s, raw[:150]); assert code(b) == 0
    s, b, raw = safe_request("POST", "entities+insert", {"collectionName": CL, "data": [{"id": 5, "vector": [0.5, 0.5, 0.5, 0.5]}]})
    print("insert pk=5:", s, raw[:200]); assert code(b) == 0
    wait_flush(CL)

    # duplicate insert same pk
    s, b, raw = safe_request("POST", "entities+insert", {"collectionName": CL, "data": [{"id": 5, "vector": [0.1, 0.1, 0.1, 0.1]}]})
    print("dup insert pk=5:", s, raw[:250])
    dup_ins_code = code(b); dup_ins_s = s
    time.sleep(2)
    _, b, raw = safe_request("POST", "entities+query", {"collectionName": CL, "filter": "id >= 0", "outputFields": ["id"]})
    qrows = (b or {}).get("data") or []
    rc_after_dup = len(qrows) if isinstance(qrows, list) else None
    print("query-visible after dup insert:", rc_after_dup, raw[:200])
    if dup_ins_s >= 500:
        print("DEFECT: dup insert -> HTTP %d" % dup_ins_s); VERDICT = "DEFECT_FOUND"; sys.exit(1)
    if dup_ins_code == 0 and rc_after_dup == 2:
        print("DEFECT: duplicate pk insert accepted AND count=2 -> pk uniqueness broken (Type4)")
        VERDICT = "DEFECT_FOUND"; sys.exit(1)

    # upsert same pk
    s, b, raw = safe_request("POST", "entities+upsert", {"collectionName": CL, "data": [{"id": 5, "vector": [0.2, 0.2, 0.2, 0.2]}]})
    print("upsert pk=5:", s, raw[:250])
    if s >= 500 or code(b) != 0:
        print("DEFECT: upsert failed: %s" % raw[:200]); VERDICT = "DEFECT_FOUND"; sys.exit(1)
    time.sleep(2)
    _, b, raw = safe_request("POST", "entities+query", {"collectionName": CL, "filter": "id >= 0", "outputFields": ["id"]})
    qrows = (b or {}).get("data") or []
    rc_after_up = len(qrows) if isinstance(qrows, list) else None
    print("query-visible after upsert:", rc_after_up, raw[:200])
    expected = 1 if rc_after_dup != 2 else 2
    if rc_after_up != expected:
        print("DEFECT: upsert changed count %s -> %s (expected %s)" % (rc_after_dup, rc_after_up, expected))
        VERDICT = "DEFECT_FOUND"; sys.exit(1)
    s, b, raw = safe_request("POST", "entities+get", {"collectionName": CL, "id": 5, "outputFields": ["vector"]})
    print("get pk=5:", s, raw[:250])
    data = (b or {}).get("data") or []
    if code(b) == 0 and isinstance(data, list) and len(data) == 1:
        v = data[0].get("vector")
        if v and abs(v[0] - 0.2) > 1e-6:
            print("DEFECT: upsert not effective; got vector %s" % v); VERDICT = "DEFECT_FOUND"; sys.exit(1)
    VERDICT = "NO_DEFECT"
except SystemExit:
    raise
except Exception as e:
    print("EXC:", repr(e)); VERDICT = "SCRIPT_ERROR"
finally:
    drop(CL)
    print("VERDICT: %s" % VERDICT)
