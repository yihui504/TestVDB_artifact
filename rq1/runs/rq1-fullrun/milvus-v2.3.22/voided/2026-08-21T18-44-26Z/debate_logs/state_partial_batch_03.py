# state_partial_batch_03.py
# Attack: partial batch failure — insert batch with one invalid row; check commit vs reported
# If code==200 but insertCount < len(data) and some valid rows silently dropped / or whole batch
# committed while error reported -> state inconsistency.
# Strategy: transaction / partial-commit detection. Blindspot: BS-03.
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

CLS = "st_part_03"
def rowcount():
    s, b, raw = req("POST", "/v2/vectordb/collections/get_stats", {"collectionName": CLS})
    if not (s == 200 and b and b.get("code") == 200):
        return None, raw[:200]
    return int((b.get("data") or {}).get("rowCount", -1)), raw

def query_ids(ids):
    s, b, raw = req("POST", "/v2/vectordb/entities/query", {
        "collectionName": CLS, "filter": f"id in {ids}", "outputFields": ["id"], "limit": 100})
    if not (s == 200 and b and b.get("code") == 200):
        return None, raw[:200]
    return [r.get("id") for r in (b.get("data") or [])], raw

try:
    try:
        req("POST", "/v2/vectordb/collections/drop", {"collectionName": CLS})
    except Exception:
        pass
    s, b, raw = req("POST", "/v2/vectordb/collections/create", {"collectionName": CLS, "dimension": 4, "autoId": False})
    print("create:", s, raw[:150])
    if not (s == 200 and b and b.get("code") == 200):
        print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
    req("POST", "/v2/vectordb/collections/load", {"collectionName": CLS})
    time.sleep(2)

    # Batch of 5: row 2 has wrong dim (3 instead of 4) -> invalid
    batch = [
        {"id": 0, "rank": 0, "vector": [0.1, 0.2, 0.3, 0.4]},
        {"id": 1, "rank": 1, "vector": [0.1, 0.2, 0.3, 0.4]},
        {"id": 2, "rank": 2, "vector": [0.1, 0.2, 0.3]},      # bad dim
        {"id": 3, "rank": 3, "vector": [0.1, 0.2, 0.3, 0.4]},
        {"id": 4, "rank": 4, "vector": [0.1, 0.2, 0.3, 0.4]},
    ]
    s, b, raw = req("POST", "/v2/vectordb/entities/insert", {"collectionName": CLS, "data": batch})
    print("mixed-dim batch insert:", s, raw[:300])
    code = (b or {}).get("code")
    time.sleep(3)

    rc, raw = rowcount()
    print("rowCount after mixed batch:", rc, raw[:150])
    got, raw = query_ids([0, 1, 2, 3, 4])
    print("query ids:", got, raw[:150])

    if code == 200:
        # reported success with an invalid row inside = Type1
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — mixed-dim batch accepted with code 200")
        sys.exit(1)
    # reported failure: nothing should be committed (atomic batch)
    if rc not in (0, None):
        present = [i for i in range(5) if got and i in got]
        if present:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — batch reported code {code} but rows committed: {present}")
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
