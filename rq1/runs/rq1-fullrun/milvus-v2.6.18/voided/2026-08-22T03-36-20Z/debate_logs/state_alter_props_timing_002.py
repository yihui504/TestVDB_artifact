# script_id: state_alter_props_timing_002
# Attack: state strategy alter_properties effective-timing (query_mode switching 16384<->1000000 window)
"""
milvus_inv_query_mode_001: query_mode == 'large_topk' <=> search limit window 1000000; unset <=> 16384.
Precondition (live): query_mode alter rejected 702 when auto-created vector index exists -> drop index first.
Sequence: create (schema-mode, no indexParams) -> drop auto index if any -> load -> insert -> alter
query_mode=large_topk -> poll search limit=20000 acceptance.
Defect: alter code 0 + describe shows large_topk but search still bound to 16384 window >5s (Type4);
or any HTTP 5xx.
"""
import sys, time
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.18\2026-08-22T03-36-20Z\debate_logs")
from _milvus_helper import safe_request, code, drop, wait_flush

CL = "st_alter_props_002"
VERDICT = "SCRIPT_ERROR"
try:
    drop(CL)
    s, b, raw = safe_request("POST", "collections+create", {"collectionName": CL, "dimension": 4})
    print("create:", s, raw[:200]); assert code(b) == 0
    # drop auto-created index so alter query_mode precondition holds (must release first: loaded coll index undroppable)
    safe_request("POST", "collections+release", {"collectionName": CL})
    s, b, raw = safe_request("POST", "indexes+list", {"collectionName": CL})
    _d = (b or {}).get("data") or []
    idxs = [i if isinstance(i, str) else i.get("indexName") for i in _d]
    print("auto indexes:", idxs)
    for nm in idxs:
        s, b, raw = safe_request("POST", "indexes+drop", {"collectionName": CL, "indexName": nm})
        print("drop index %s:" % nm, raw[:150])
        if code(b) != 0:
            print("cannot drop index -> alter precondition unattainable; exit no-defect")
            VERDICT = "NO_DEFECT"; sys.exit(0)
    # alter BEFORE load (index dropped): alter is only legal while no vector index exists
    s, b, raw = safe_request("POST", "entities+insert", {"collectionName": CL, "data": [
        {"id": i, "vector": [0.1 * i, 0.2, 0.3, 0.4]} for i in range(1, 6)]})
    print("insert:", s, raw[:150])

    s, b, raw = safe_request("POST", "collections+alter_properties", {
        "collectionName": CL, "properties": {"query_mode": "large_topk"}})
    print("alter query_mode:", s, raw[:300])
    if s >= 500:
        print("DEFECT: alter_properties -> HTTP %d" % s); VERDICT = "DEFECT_FOUND"; sys.exit(1)
    if code(b) != 0:
        print("alter rejected (non-500):", raw[:200]); VERDICT = "NO_DEFECT"; sys.exit(0)

    # recreate index + load, then baseline check must now be the LARGE window
    s, b, raw = safe_request("POST", "indexes+create", {"collectionName": CL, "indexParams": [
        {"fieldName": "vector", "indexName": "vector", "indexType": "FLAT", "metricType": "L2"}]})
    print("recreate index:", s, raw[:150])
    s, b, raw = safe_request("POST", "collections+load", {"collectionName": CL})
    print("load:", s, raw[:150])
    import time as _t
    for _ in range(15):
        _, bl,rawl = safe_request("POST", "collections+get_load_state", {"collectionName": CL})
        if "LoadStateLoaded" in rawl: break
        _t.sleep(1)
    # sanity: normal limit still fine
    s, b, raw = safe_request("POST", "entities+search", {"collectionName": CL,
        "data": [[0.1, 0.2, 0.3, 0.4]], "limit": 5, "annsField": "vector"})
    print("sanity search limit=5:", s, raw[:150])

    accepted = False; last_raw = ""
    for attempt in range(6):
        s, b, raw = safe_request("POST", "entities+search", {"collectionName": CL,
            "data": [[0.1, 0.2, 0.3, 0.4]], "limit": 20000, "annsField": "vector"})
        last_raw = raw
        print("post-alter search attempt %d: %s %s" % (attempt, s, raw[:160]))
        if s >= 500:
            print("DEFECT: search after alter -> HTTP %d" % s); VERDICT = "DEFECT_FOUND"; sys.exit(1)
        if code(b) == 0:
            accepted = True; break
        time.sleep(1)
    if not accepted and "16384" in last_raw:
        _, b2, raw2 = safe_request("POST", "collections+describe", {"collectionName": CL})
        has_prop = "large_topk" in raw2
        print("describe has query_mode:", has_prop)
        if has_prop:
            print("DEFECT: alter code 0 + describe shows large_topk but search still bound to 16384 window >5s (Type4)")
            VERDICT = "DEFECT_FOUND"; sys.exit(1)
    try:
        safe_request("POST", "collections+drop_properties", {"collectionName": CL, "propertyKeys": ["query_mode"]})
    except Exception:
        pass
    VERDICT = "NO_DEFECT"
except SystemExit:
    raise
except Exception as e:
    print("EXC:", repr(e)); VERDICT = "SCRIPT_ERROR"
finally:
    drop(CL)
    print("VERDICT: %s" % VERDICT)
