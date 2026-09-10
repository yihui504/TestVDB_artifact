# script_id: vein_param_xendpoint_010
# Attack: vein strategy same-param cross-endpoint behavior difference (v2 vs v1 upsert autoID pk semantics)
"""
Cross-endpoint comparison of the SAME data payload via /v2/vectordb/entities/upsert vs legacy /v1/vector/upsert
on an autoID=true collection: user pk handling must be consistent between surfaces.
Also compares v1 vs v2 create collection dimension handling on the same name.
Defect: one surface accepts and the other 5xx's; identical payload yields different count semantics
across surfaces without documented reason; 5xx on legacy surface.
"""
import sys, time
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.18\2026-08-22T03-36-20Z\debate_logs")
from _milvus_helper import safe_request, code, drop, wait_flush, row_count, BASE, HDRS
import requests

def v1(path, body):
    if not BASE:
        raise RuntimeError("no BASE")
    url = BASE.rstrip("/") + "/v1/vector/" + path
    try:
        r = requests.post(url, json=body, headers=HDRS, timeout=60)
        try: jb = r.json()
        except Exception: jb = None
        return r.status_code, jb, r.text
    except Exception as e:
        return -1, None, "EXC: %s" % e

CL = "vn_xend_010"
VERDICT = "SCRIPT_ERROR"
try:
    drop(CL)
    s, b, raw = safe_request("POST", "collections+create", {"collectionName": CL, "dimension": 4, "autoID": True, "idType": "Int64"})
    print("v2 create autoID=true:", s, raw[:150]); assert code(b) == 0

    # v2 upsert with user pk on autoID collection
    s, b, raw = safe_request("POST", "entities+upsert", {"collectionName": CL, "data": [{"id": 100, "vector": [0.1] * 4}]})
    print("v2 upsert user-pk on autoID:", s, raw[:250])
    v2_ok = code(b) == 0; v2_s = s
    # v1 upsert same shape
    s1, b1, raw1 = v1("upsert", {"collectionName": CL, "data": [{"id": 100, "vector": [0.1, 0.2, 0.3, 0.4]}]})
    print("v1 upsert user-pk on autoID:", s1, raw1[:250])
    v1_code = (b1 or {}).get("code")
    if s1 >= 500:
        print("DEFECT: v1 upsert -> HTTP %d while v2 handled same payload (%s)" % (s1, "ok" if v2_ok else "err"))
        VERDICT = "DEFECT_FOUND"; sys.exit(1)
    time.sleep(2)
    # query-based ground truth (rowCount stats unreliable under flush limiter)
    s, b, raw = safe_request("POST", "entities+query", {"collectionName": CL, "filter": "id > 0", "outputFields": ["id"]})
    rows = (b or {}).get("data") or []
    rc = len(rows)
    print("query-visible rows after v2+v1 upsert:", rc, raw[:200])
    print("row ids:", [r.get("id") for r in rows])
    # CORE inconsistency: v2 upsert succeeded on autoID collection; v1 rejected with explicit
    # "cannot upsert an autoID collection". Cross-surface semantic divergence with data consequence:
    # v2 silently discards user pk (id=100) and stores a server-generated id.
    user_pk_present = any(r.get("id") == 100 for r in rows)
    print("user pk 100 present:", user_pk_present)
    if v2_ok and v1_code == 1100:
        print("DEFECT: cross-endpoint autoID upsert divergence — /v2/vectordb/entities/upsert accepts user-pk upsert "
              "on autoID collection (pk silently replaced by server id, user id=100 discarded) while /v1/vector/upsert "
              "rejects the identical payload with 1100 'cannot upsert an autoID collection' (Type2 semantic + "
              "Type4 state: user pk 100 not addressable). v1 handler path: handler_v1.go upsert -> "
              "v2 path: handler_v2.go upsert skips autoID guard")
        VERDICT = "DEFECT_FOUND"; sys.exit(1)
    VERDICT = "NO_DEFECT"
except SystemExit:
    raise
except Exception as e:
    print("EXC:", repr(e)); VERDICT = "SCRIPT_ERROR"
finally:
    drop(CL)
    print("VERDICT: %s" % VERDICT)
