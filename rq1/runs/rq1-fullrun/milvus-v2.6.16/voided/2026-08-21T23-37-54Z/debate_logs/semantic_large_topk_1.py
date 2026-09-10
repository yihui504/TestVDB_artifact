# script_id: semantic_large_topk_1
# Attack: large_topk 语义正确性——large_topk 模式与普通模式结果一致性 + limit/offset 边界
# Constraints: milvus_range_entities_search_001, milvus_range_entities_search_003, milvus_inv_query_mode_001
# source_url: .milvus-src-2616 (contract), doc_version: unknown
import os, sys, time
import requests

BASE = os.environ.get("TESTVDB_DB_URL")
TOKEN = os.environ.get("TESTVDB_DB_TOKEN", "root:Milvus")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
H = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}

def sr(path, body=None):
    try:
        r = requests.post(BASE + "/v2/vectordb/" + path, json=body if body is not None else {}, headers=H, timeout=120)
        raw = r.text
        try:
            b = r.json()
        except Exception:
            b = None
        return r.status_code, b, raw
    except Exception as e:
        return -1, None, str(e)

CL_N = "sm_ltk_normal"
CL_L = "sm_ltk_large"

def cleanup():
    for c in [CL_N, CL_L]:
        try: sr("collections/drop", {"collectionName": c})
        except Exception: pass

def mk(name, large):
    # v2.6.16 create-time `properties` is silently discarded (CollectionReq has no such
    # field, source: handler_v2.go createCollection) -> must use alter_properties path.
    body = {"collectionName": name,
            "schema": {"fields": [
                {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
                {"fieldName": "vector", "dataType": "FloatVector",
                 "elementTypeParams": {"dim": "4"}}]}}
    s, b, raw = sr("collections/create", body)
    if large and isinstance(b, dict) and b.get("code") == 0:
        s2, b2, raw2 = sr("collections/alter_properties",
            {"collectionName": name, "properties": {"query_mode": "large_topk"}})
        print("mk alter qm", name, ":", s2, raw2[:120])
        # forward order is allowed: index AFTER large_topk
        sr("indexes/create", {"collectionName": name, "indexParams": [
            {"fieldName": "vector", "indexName": "idx", "indexType": "FLAT", "metricType": "L2"}]})
    return s, b, raw

def search(name, limit=None, offset=None, data=None):
    b = {"collectionName": name, "data": data or [[0.1, 0.2, 0.3, 0.4]],
         "outputFields": ["id"], "consistencyLevel": "Strong"}
    if limit is not None: b["limit"] = limit
    if offset is not None: b["offset"] = offset
    return sr("entities/search", b)

def ids_of(b):
    d = (b or {}).get("data") if isinstance(b, dict) else None
    if d and isinstance(d, list) and d and isinstance(d[0], dict):
        return [x.get("id") for x in d]
    return None

def main():
    defects = []
    cleanup(); time.sleep(1)
    N = 500  # limit tests probe quota, not data volume
    for name, large in [(CL_N, False), (CL_L, True)]:
        s, b, raw = mk(name, large)
        print("create", name, ":", s, raw[:200])
        if not (isinstance(b, dict) and b.get("code") == 0):
            print("VERDICT: SCRIPT_ERROR"); cleanup(); sys.exit(2)
        if not large:
            sr("indexes/create", {"collectionName": name, "indexParams": [
                {"fieldName": "vector", "indexName": "idx", "indexType": "FLAT", "metricType": "L2"}]})
    # F: create-time properties must be silently discarded -> explicit defect check
    s, b, raw = sr("collections/create", {"collectionName": CL_L + "_ct",
        "schema": {"fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "vector", "dataType": "FloatVector", "elementTypeParams": {"dim": "4"}}]},
        "properties": {"query_mode": "large_topk"}})
    print("F create with properties:", s, raw[:150])
    if isinstance(b, dict) and b.get("code") == 0:
        s2, b2, raw2 = sr("collections/describe", {"collectionName": CL_L + "_ct"})
        props = (b2 or {}).get("data", {}).get("properties") if isinstance(b2, dict) else None
        has_qm = any((p.get("key") == "query_mode") for p in (props or []) if isinstance(p, dict)) if isinstance(props, list) else ("query_mode" in (props or {}))
        print("F query_mode persisted via create-time properties:", has_qm, str(props)[:120])
        if not has_qm:
            defects.append(("create-time properties.query_mode silently discarded (code 0, no effect, no warning) — violates create_009/inv_query_mode_001", str(props)[:150]))
        try: sr("collections/drop", {"collectionName": CL_L + "_ct"})
        except Exception: pass
    rows = [{"id": i, "vector": [0.001 * (i % 5)] * 4} for i in range(N)]
    for name in [CL_N, CL_L]:
        for off in range(0, N, 5000):
            s, b, raw = sr("entities/insert", {"collectionName": name, "data": rows[off:off + 5000]})
            if not (isinstance(b, dict) and b.get("code") == 0):
                print("insert fail", name, raw[:150]); print("VERDICT: SCRIPT_ERROR"); cleanup(); sys.exit(2)
        sr("collections/load", {"collectionName": name})
    time.sleep(3)

    # A: normal-mode search limit beyond 16384 -> rejected (quota), large_topk -> accepted
    s, b, raw = search(CL_N, limit=20000)
    print("A normal limit=20000:", s, raw[:200])
    code = b.get("code") if isinstance(b, dict) else None
    if code == 0:
        defects.append(("normal query_mode ACCEPTED limit=20000 (quota not enforced)", raw[:150]))
    elif code not in (65535, 1100):
        defects.append(("normal-mode over-limit search returns unexpected code %s" % code, raw[:150]))
    else:
        # diagnostic quality: message must state the actual bound (16384)
        msg = str(b.get("message"))
        if "16384" not in msg:
            defects.append(("over-limit message omits actual bound 16384", msg[:150]))
    s, b, raw = search(CL_L, limit=20000)
    print("A large limit=20000:", s, raw[:200])
    if not (isinstance(b, dict) and b.get("code") == 0):
        defects.append(("large_topk mode rejected limit=20000", raw[:150]))
    else:
        n = len((b.get("data") or []))
        if n != N:
            defects.append(("large_topk limit=20000 returned %s results (expected %s)" % (n, N), ""))

    # B: result-set equivalence at common limit (100): normal vs large_topk ordering must match
    s1, b1, _ = search(CL_N, limit=100)
    s2, b2, _ = search(CL_L, limit=100)
    i1, i2 = ids_of(b1), ids_of(b2)
    print("B normal ids[:10]:", (i1 or [])[:10], "| large ids[:10]:", (i2 or [])[:10])
    if i1 is not None and i2 is not None and i1 != i2:
        diff = sum(1 for a, c in zip(i1, i2) if a != c)
        defects.append(("result ordering differs between normal and large_topk at limit=100: %d/%d mismatch" % (diff, len(i1)), ""))

    # C: offset+limit window semantics (large mode): offset 100, limit 50 -> ids [100..149]-ish distinct from page 1
    sp, bp, _ = search(CL_L, limit=50)
    sq, bq, _ = search(CL_L, limit=50, offset=50)
    ip, iq = ids_of(bp), ids_of(bq)
    if ip and iq:
        overlap = set(ip) & set(iq)
        print("C page1/page2 overlap:", len(overlap))
        if overlap:
            defects.append(("offset window overlaps previous page: %s shared ids" % len(overlap), ""))

    # D: boundary offsets in large mode: offset+limit == 1000000 exactly vs +1 over
    s, b, raw = search(CL_L, limit=1, offset=999999)
    print("D offset+limit==1000000:", s, raw[:200])
    code = b.get("code") if isinstance(b, dict) else None
    if code not in (0,):  # window at cap must be accepted (result may be empty)
        defects.append(("large_topk rejected offset+limit==1000000 exactly: code %s" % code, raw[:150]))
    s, b, raw = search(CL_L, limit=1, offset=1000000)
    print("D offset==1000000:", s, raw[:200])
    code = b.get("code") if isinstance(b, dict) else None
    if code == 0:
        defects.append(("large_topk ACCEPTED offset=1000000 (beyond 1000000 window)", raw[:150]))

    cleanup()
    for d in defects: print("DEFECT:", d)
    if defects:
        print("VERDICT: DEFECT_FOUND"); sys.exit(1)
    print("VERDICT: NO_DEFECT"); sys.exit(0)

try:
    main()
except Exception as e:
    print("EXC:", e)
    try: cleanup()
    except Exception: pass
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
