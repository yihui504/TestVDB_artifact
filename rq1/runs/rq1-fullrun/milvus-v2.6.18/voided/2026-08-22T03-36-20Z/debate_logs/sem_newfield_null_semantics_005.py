# script_id: sem_newfield_null_semantics_005
# Attack: semantic strategy fields+add scalar field -> old rows null semantics (query/filter on new field)
"""
Add nullable scalar field via collections+fields+add. Old rows (written pre-add) must read as null/absent
for the new field; filtering on new field must not error nor return old rows unexpectedly.
Defect: query filter on new field -> HTTP 500 / code unexpected; get old row returns fabricated non-null
default (e.g. 0) instead of null (semantic violation of nullable).
"""
import sys
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.18\2026-08-22T03-36-20Z\debate_logs")
from _milvus_helper import safe_request, code, drop, wait_flush

CL = "sem_newfield_null_005"
VERDICT = "SCRIPT_ERROR"
try:
    drop(CL)
    s, b, raw = safe_request("POST", "collections+create", {
        "collectionName": CL, "dimension": 4, "autoID": False, "idType": "Int64"})
    print("create:", s, raw[:150]); assert code(b) == 0
    s, b, raw = safe_request("POST", "entities+insert", {"collectionName": CL, "data": [
        {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}]})
    print("insert pre-add:", s, raw[:150]); assert code(b) == 0
    wait_flush(CL)
    s, b, raw = safe_request("POST", "collections+fields+add", {
        "collectionName": CL,
        "schema": {"fieldName": "score", "dataType": "Int64", "nullable": True}})
    print("fields+add score:", s, raw[:300])
    if code(b) != 0:
        print("fields+add rejected; noting and exiting no-defect for this surface")
        VERDICT = "NO_DEFECT"; sys.exit(0)
    # insert a row with score
    s, b, raw = safe_request("POST", "entities+insert", {"collectionName": CL, "data": [
        {"id": 2, "vector": [0.5, 0.6, 0.7, 0.8], "score": 42}]})
    print("insert with score:", s, raw[:200])
    wait_flush(CL)

    # old row null semantics
    s, b, raw = safe_request("POST", "entities+get", {"collectionName": CL, "id": 1, "outputFields": ["score"]})
    print("get old row score:", s, raw[:300])
    if s >= 500:
        print("DEFECT: get old row new field -> HTTP %d" % s); VERDICT = "DEFECT_FOUND"; sys.exit(1)
    data = (b or {}).get("data") or []
    if code(b) == 0 and data:
        sc = data[0].get("score")
        if sc not in (None,):  # fabricated default = semantic violation
            # allow documented 0? record as observation first
            if sc == 0:
                print("OBS: old row new Int64 field returns 0 (fabricated default, not null) — flag")
                print("DEFECT: nullable new field reads back 0 for pre-existing row instead of null (Type2 semantic)")
                VERDICT = "DEFECT_FOUND"; sys.exit(1)
            else:
                print("OBS unexpected score value:", sc)

    # filter on new field: old rows must not match score == 42; no 500
    s, b, raw = safe_request("POST", "entities+query", {"collectionName": CL,
        "filter": "score == 42", "outputFields": ["id", "score"]})
    print("query score==42:", s, raw[:300])
    if s >= 500:
        print("DEFECT: query filter on added field -> HTTP %d" % s); VERDICT = "DEFECT_FOUND"; sys.exit(1)
    if code(b) == 0:
        rows = (b or {}).get("data") or []
        ids = [r.get("id") for r in rows]
        print("matched ids:", ids)
        if 1 in ids:
            print("DEFECT: old row (null score) matched score==42 filter (Type2)"); VERDICT = "DEFECT_FOUND"; sys.exit(1)
    VERDICT = "NO_DEFECT"
except SystemExit:
    raise
except Exception as e:
    print("EXC:", repr(e)); VERDICT = "SCRIPT_ERROR"
finally:
    drop(CL)
    print("VERDICT: %s" % VERDICT)
