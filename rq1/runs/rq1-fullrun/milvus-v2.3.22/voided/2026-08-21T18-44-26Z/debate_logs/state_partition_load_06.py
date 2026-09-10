# state_partition_load_06.py
# Attack: partition vs collection load semantics cross-check.
# - partition load on NotLoad collection: collection loadState / other partition searchable?
# - partition release while collection Loaded
# - insert into released partition
# Strategy: index_state / state machine. Blindspot: BS-03.
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

CLS, P1, P2 = "st_part_06", "p1x", "_default"

def create():
    return req("POST", "/v2/vectordb/collections/create", {"collectionName": CLS, "dimension": 4, "autoId": False})

def load_state():
    s, b, raw = req("POST", "/v2/vectordb/collections/get_load_state", {"collectionName": CLS})
    if not (s == 200 and b and b.get("code") == 200):
        return ("ERR", raw[:150])
    return ((b.get("data") or {}).get("loadState"), (b.get("data") or {}).get("progress")), raw[:150]

def insert(part, n, start):
    rows = [{"id": start + i, "vector": [0.1, 0.2, 0.3, 0.4]} for i in range(n)]
    return req("POST", "/v2/vectordb/entities/insert", {"collectionName": CLS, "partitionName": part, "data": rows})

def query_all():
    s, b, raw = req("POST", "/v2/vectordb/entities/query", {
        "collectionName": CLS, "filter": "id >= 0", "outputFields": ["id"], "limit": 100})
    return s, (b or {}).get("code"), len((b or {}).get("data") or []), raw[:200]

try:
    try:
        req("POST", "/v2/vectordb/collections/drop", {"collectionName": CLS})
    except Exception:
        pass
    s, b, raw = create()
    print("create:", s, raw[:150])
    if not (s == 200 and b and b.get("code") == 200):
        print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
    s, b, raw = req("POST", "/v2/vectordb/partitions/create", {"collectionName": CLS, "partitionName": P1})
    print("create partition:", s, raw[:150])

    # 1. load partition only while collection NotLoad
    s, b, raw = req("POST", "/v2/vectordb/partitions/load", {"collectionName": CLS, "partitionNames": [P1]})
    print("partition load P1:", s, raw[:200])
    time.sleep(2)
    print("collection loadState after partition load:", load_state())

    s, b, raw = insert(P1, 3, 0)
    print("insert into P1:", s, raw[:150])
    s, b, raw = insert(P2, 3, 100)
    print("insert into _default (not partition-loaded):", s, raw[:200])

    # query with partitions filter — only loaded partitions should be queried
    time.sleep(3)  # bounded consistency lag
    s, b, raw = req("POST", "/v2/vectordb/entities/query", {
        "collectionName": CLS, "partitionNames": [P1], "filter": "id >= 0", "outputFields": ["id"], "limit": 100})
    print("query P1 only (after lag):", s, raw[:250])
    if (b or {}).get("code") == 200 and len((b or {}).get("data") or []) != 3:
        print(f"DEFECT_CANDIDATE Type4: partition P1 loaded, expected 3 rows, saw {len((b or {}).get('data') or [])}")
    s, b, raw = req("POST", "/v2/vectordb/entities/query", {
        "collectionName": CLS, "partitionNames": [P2], "filter": "id >= 0", "outputFields": ["id"], "limit": 100})
    print("query P2 only (not loaded):", s, raw[:250])

    # 2. release the loaded partition
    s, b, raw = req("POST", "/v2/vectordb/partitions/release", {"collectionName": CLS, "partitionNames": [P1]})
    print("partition release P1:", s, raw[:200])
    time.sleep(1)
    print("collection loadState after partition release:", load_state())
    s, b, raw = req("POST", "/v2/vectordb/entities/query", {
        "collectionName": CLS, "partitionNames": [P1], "filter": "id >= 0", "outputFields": ["id"], "limit": 100})
    print("query released P1:", s, raw[:250])
    if (b or {}).get("code") == 65535:
        print("DEFECT_CANDIDATE Type3/Type4: query on released partition returns UnexpectedError(65535) instead of structured 101 not-loaded")

    # 3. insert into released partition — should still succeed (write doesn't need load)
    s, b, raw = insert(P1, 2, 50)
    print("insert into released P1:", s, raw[:200])

    # 4. full collection load -> everything queryable
    req("POST", "/v2/vectordb/collections/load", {"collectionName": CLS})
    time.sleep(3)
    s, code, n, raw = query_all()
    print(f"query all after full load: http {s} code {code} rows {n} {raw}")
    if code == 200 and n not in (8,):
        print(f"DEFECT_CANDIDATE Type4: expected 8 total rows (3+3+2), got {n}")

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
