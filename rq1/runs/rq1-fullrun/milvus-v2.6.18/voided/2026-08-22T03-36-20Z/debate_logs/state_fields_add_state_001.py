# script_id: state_fields_add_state_001
# Attack: state strategy fields+add state consistency (schema visibility vs data write acceptance vs old-row null semantics vs index build)
"""
collections+fields+add vector field (nullable, dim 4) to an existing loaded collection.
Verifications:
 A. describe shows new field immediately (describe uses 'fields[].name')
 B. insert of new rows WITHOUT the new vector field -> accepted (nullable) or clean reject
 C. entities/get on old rows with outputFields=[newfield] -> null semantics (record)
 D. index creation on new vector field while old rows have null vectors -> no 500
Defect signals: HTTP 5xx anywhere; insert accepted but later get/query 5xx (state divergence).
"""
import sys, time, json
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.18\2026-08-22T03-36-20Z\debate_logs")
from _milvus_helper import safe_request, code, drop, wait_flush

CL = "st_fields_add_001"
VERDICT = "SCRIPT_ERROR"
try:
    drop(CL)
    s, b, raw = safe_request("POST", "collections+create", {
        "collectionName": CL, "dimension": 4, "autoID": False, "idType": "Int64"})
    print("create:", s, raw[:200]); assert code(b) == 0, "setup create failed"
    s, b, raw = safe_request("POST", "entities+insert", {"collectionName": CL, "data": [
        {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}]})
    print("insert old row:", s, raw[:200]); assert code(b) == 0, "setup insert failed"
    # (skip flush here to avoid flush RateLimiter)

    # A. add new nullable vector field
    s, b, raw = safe_request("POST", "collections+fields+add", {
        "collectionName": CL,
        "schema": {"fieldName": "vec2", "dataType": "FloatVector",
                   "nullable": True, "elementTypeParams": {"dim": "4"}}})
    print("fields+add vec2:", s, raw[:300])
    add_code = code(b)
    s2, b2, raw2 = safe_request("POST", "collections+describe", {"collectionName": CL})
    names = [f.get("name") for f in ((b2 or {}).get("data") or {}).get("fields", [])]
    print("describe fields after add:", names, "add_code:", add_code)
    schema_has = "vec2" in (names or [])
    if add_code == 0 and not schema_has:
        print("DEFECT: fields+add code 0 but describe lacks field (visibility lag)"); VERDICT = "DEFECT_FOUND"; sys.exit(1)
    if add_code != 0:
        print("fields+add rejected; schema-add-vector unsupported here -> report and stop cleanly")
        VERDICT = "NO_DEFECT"; sys.exit(0)

    # B. insert new row without vec2
    s, b, raw = safe_request("POST", "entities+insert", {"collectionName": CL, "data": [
        {"id": 2, "vector": [0.5, 0.6, 0.7, 0.8]}]})
    print("insert without vec2:", s, raw[:300])
    if s >= 500:
        print("DEFECT: insert after fields+add -> HTTP %d (server error)" % s); VERDICT = "DEFECT_FOUND"; sys.exit(1)
    insert_ok = code(b) == 0
    print("insert_without_newfield accepted:", insert_ok)

    # C. old row null semantics via get
    s, b, raw = safe_request("POST", "entities+get", {"collectionName": CL, "id": 1, "outputFields": ["vec2"]})
    print("get old row vec2:", s, raw[:300])
    if s >= 500:
        print("DEFECT: get with new-field outputFields -> HTTP %d" % s); VERDICT = "DEFECT_FOUND"; sys.exit(1)

    # D. index on new vector field while old rows have null vec2
    s, b, raw = safe_request("POST", "indexes+create", {"collectionName": CL, "indexParams": [
        {"fieldName": "vec2", "indexName": "vec2_idx", "indexType": "FLAT", "metricType": "L2"}]})
    print("index create on vec2:", s, raw[:300])
    if s >= 500:
        print("DEFECT: index create on added nullable vector field -> HTTP %d" % s); VERDICT = "DEFECT_FOUND"; sys.exit(1)
    if code(b) == 0:
        for i in range(20):
            s, b, raw = safe_request("POST", "indexes+describe", {"collectionName": CL, "indexName": "vec2_idx"})
            if "Finished" in raw or (isinstance((b or {}).get("data"), dict) and (b or {}).get("data", {}).get("state") == "Finished"):
                print("index finished after %d polls" % i); break
            time.sleep(1)
        else:
            print("OBS: index on null-vector field still not finished after 20s (acceptable async)")
    # E. final data consistency: single flush + query-based presence check
    wait_flush(CL)
    _, b, raw = safe_request("POST", "entities+query", {"collectionName": CL, "filter": "id >= 1", "outputFields": ["id"]})
    print("final query:", raw[:300])
    ids_found = [r.get("id") for r in ((b or {}).get("data") or [])]
    expected_ids = [1, 2] if insert_ok else [1]
    if code(b) == 0 and sorted(ids_found) != sorted(expected_ids):
        print("DEFECT: post-fields+add query ids=%s expected=%s (data loss/ghost rows)" % (ids_found, expected_ids))
        VERDICT = "DEFECT_FOUND"; sys.exit(1)
    _, b, raw = safe_request("POST", "collections+get_stats", {"collectionName": CL})
    print("final stats:", raw[:200])
    VERDICT = "NO_DEFECT"
except SystemExit:
    raise
except Exception as e:
    print("EXC:", repr(e)); VERDICT = "SCRIPT_ERROR"
finally:
    drop(CL)
    print("VERDICT: %s" % VERDICT)
