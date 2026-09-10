# script_id: state_upsert_autoid_003
# Attack: state strategy upsert idempotence on autoID=true collection (Type4 state semantics)
"""
milvus_inv_upsert_atomic_001 + contract note: 'On autoID=true collections upsert ignores user pk and
inserts new auto-generated id (live v2.6.18)'.
Test matrix:
 1. upsert same user pk (id=100) twice on autoID=true collection -> count and id semantics.
    If each upsert creates a NEW auto id -> count grows by 2 (documented-by-contract quirk, record).
 2. On autoID=false collection: upsert same pk twice -> count must stay 1, get returns last-write values (idempotence invariant).
Defect signals (Type4): autoID=false count != 1 after duplicate upsert; get returns stale/first-write values; HTTP 500.
"""
import sys
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.18\2026-08-22T03-36-20Z\debate_logs")
from _milvus_helper import safe_request, code, drop, wait_flush, row_count

CL_A = "st_upsert_auto_003a"   # autoID=true
CL_M = "st_upsert_manual_003b" # autoID=false
VERDICT = "SCRIPT_ERROR"
try:
    for cl, auto in ((CL_A, True), (CL_M, False)):
        drop(cl)
        s, b, raw = safe_request("POST", "collections+create", {
            "collectionName": cl, "dimension": 4, "autoID": auto, "idType": "Int64"})
        print("create %s auto=%s:" % (cl, auto), s, raw[:150]); assert code(b) == 0

    # --- autoID=true: upsert twice with same user pk ---
    ids_returned = []
    for i in range(2):
        s, b, raw = safe_request("POST", "entities+upsert", {"collectionName": CL_A,
            "data": [{"id": 100, "vector": [0.1, 0.2, 0.3, 0.4]}]})
        print("upsert autoID #%d:" % i, s, raw[:250])
        if s >= 500:
            print("DEFECT: upsert on autoID collection -> HTTP %d" % s); VERDICT = "DEFECT_FOUND"; sys.exit(1)
        if code(b) == 0:
            try:
                ids_returned.append((b.get("data") or {}).get("upsertIds"))
            except Exception:
                pass
    wait_flush(CL_A)
    # rowCount (get_stats) lags behind rate-limited flushes; use query-based ground truth instead
    s, b, raw = safe_request("POST", "entities+query", {"collectionName": CL_A, "filter": "id > 0", "outputFields": ["id"]})
    print("autoID query after 2 identical upserts:", s, raw[:300])
    qrows = (b or {}).get("data") or []
    rc = len(qrows) if isinstance(qrows, list) else None
    print("upsertIds:", ids_returned, "query-visible rows:", rc)
    if rc is not None and rc not in (1, 2):
        print("DEFECT: autoID upsert twice -> visible rows %s (expected 1 or 2)" % rc); VERDICT = "DEFECT_FOUND"; sys.exit(1)

    # --- autoID=false: idempotence ---
    for vec in ([0.9, 0.8, 0.7, 0.6], [0.1, 0.1, 0.1, 0.1]):
        s, b, raw = safe_request("POST", "entities+upsert", {"collectionName": CL_M,
            "data": [{"id": 7, "vector": vec}]})
        print("upsert manual:", s, raw[:250])
        if s >= 500 or code(b) != 0:
            print("DEFECT: manual upsert failed: %s" % raw[:200]); VERDICT = "DEFECT_FOUND"; sys.exit(1)
    wait_flush(CL_M)
    s, b, raw = safe_request("POST", "entities+query", {"collectionName": CL_M, "filter": "id >= 0", "outputFields": ["id"]})
    qrows = (b or {}).get("data") or []
    rc = len(qrows) if isinstance(qrows, list) else None
    print("manual query-visible rows after 2 pk=7 upserts:", rc, raw[:200])
    if rc != 1:
        print("DEFECT: upsert not idempotent, rowCount=%s expected 1 (Type4)" % rc); VERDICT = "DEFECT_FOUND"; sys.exit(1)
    s, b, raw = safe_request("POST", "entities+get", {"collectionName": CL_M, "id": 7, "outputFields": ["vector"]})
    print("get pk=7:", s, raw[:250])
    got = (b or {}).get("data") or []
    if code(b) == 0 and got:
        v = got[0].get("vector")
        if v and abs(v[0] - 0.1) > 1e-6:
            print("DEFECT: get after upsert returned first-write vector %s (last-write-wins violated)" % v)
            VERDICT = "DEFECT_FOUND"; sys.exit(1)
    VERDICT = "NO_DEFECT"
except SystemExit:
    raise
except Exception as e:
    print("EXC:", repr(e)); VERDICT = "SCRIPT_ERROR"
finally:
    drop(CL_A); drop(CL_M)
    print("VERDICT: %s" % VERDICT)
