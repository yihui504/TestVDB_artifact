# state_count_consistency_02.py
# Attack: milvus_inv_count_consistency — insert N (incl. duplicate-PK upsert) -> get_stats rowCount == N
# Strategy: count_consistency / upsert_idempotence
import os, sys, time, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530")
HDR = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}

def req(method, path, body=None):
    try:
        r = requests.request(method, BASE_URL + path, headers=HDR, json=body if body is not None else {}, timeout=60)
        try:
            b = r.json()
        except Exception:
            b = None
        return r.status_code, b, r.text
    except Exception as e:
        return -1, None, str(e)

CLS = "st_cnt_02"
def rowcount():
    s, b, raw = req("POST", "/v2/vectordb/collections/get_stats", {"collectionName": CLS})
    if not (s == 200 and b and b.get("code") == 200):
        return None, raw[:200]
    d = b.get("data") or {}
    return int(d.get("rowCount", -1)), raw

try:
    try:
        req("POST", "/v2/vectordb/collections/drop", {"collectionName": CLS})
    except Exception:
        pass
    s, b, raw = req("POST", "/v2/vectordb/collections/create", {"collectionName": CLS, "dimension": 4, "autoId": False})
    print("create:", s, raw[:150])
    req("POST", "/v2/vectordb/collections/load", {"collectionName": CLS})
    time.sleep(2)

    N1 = 10
    s, b, raw = req("POST", "/v2/vectordb/entities/insert", {"collectionName": CLS, "data": [
        {"id": i, "vector": [0.1, 0.2, 0.3, 0.4]} for i in range(N1)]})
    print("insert N1:", s, raw[:200])

    # upsert same PKs twice — count must stay N1 (idempotent, no dup rows)
    for rnd in range(2):
        s, b, raw = req("POST", "/v2/vectordb/entities/upsert", {"collectionName": CLS, "data": [
            {"id": i, "vector": [0.5, 0.5, 0.5, 0.5]} for i in range(N1)]})
        print(f"upsert round {rnd}:", s, raw[:150])

    time.sleep(3)
    rc, raw = rowcount()
    print("get_stats rowCount (informational, may lag on standalone):", rc, raw[:150])
    s, b, raw = req("POST", "/v2/vectordb/entities/query", {
        "collectionName": CLS, "filter": "id >= 0", "outputFields": ["id"], "limit": 1000})
    print("query count check:", s, raw[:250])
    seen = None
    if s == 200 and b and b.get("code") == 200:
        seen = len(b.get("data") or [])
        ids = [r.get("id") for r in (b.get("data") or [])]
        if seen != N1 or len(set(ids)) != N1:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — after insert+2x upsert expected {N1} unique rows, query sees {seen} (unique {len(set(ids))})")
            sys.exit(1)
        # last write wins: vector should be [0.5,0.5,0.5,0.5]
    else:
        print("query failed — treat as script error"); sys.exit(2)

    # delete half, verify count
    s, b, raw = req("POST", "/v2/vectordb/entities/delete", {"collectionName": CLS, "filter": "id < 5 "})
    print("delete id<5:", s, raw[:150])
    time.sleep(2)
    s, b, raw = req("POST", "/v2/vectordb/entities/query", {
        "collectionName": CLS, "filter": "id >= 0", "outputFields": ["id"], "limit": 1000})
    seen2 = len((b or {}).get("data") or []) if (s == 200 and (b or {}).get("code") == 200) else None
    print("query rows after delete id<5:", seen2, raw[:200])
    if seen2 != 5:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — after deleting id<5 expected 5 rows, query sees {seen2}")
        sys.exit(1)

    print("VERDICT: NO_DEFECT")
    sys.exit(0)
except Exception as e:
    print("EXC:", e)
    print("VERDICT: SCRIPT_ERROR")
    sys.exit(2)
finally:
    try:
        req("POST", "/v2/vectordb/collections/drop", {"collectionName": CLS})
    except Exception:
        pass
