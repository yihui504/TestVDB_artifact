# state_count_consistency_03.py
# Attack: state_invariant milvus_inv_count_consistency_001 — insert N -> get_stats rowCount == N
# Covers: entities+insert / collections+flush / collections+get_stats / entities+delete / entities+upsert
# Blindspot: BS-03 (visibility semantics under flush)
import os, sys, time, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
BASE_URL = BASE_URL.rstrip("/")
H = {"Content-Type": "application/json", "Authorization": "Bearer root:Milvus"}
CLS = "stt_count_03"; DIM = 4

def safe_request(method, path, payload=None):
    try:
        r = requests.request(method, f"{BASE_URL}/v2/vectordb/{path}", headers=H, json=payload or {}, timeout=60)
        try: body = r.json()
        except Exception: body = None
        return r.status_code, body, r.text
    except Exception as e:
        return -1, None, f"EXC:{e}"

def ok(b): return b is not None and b.get("code") == 0

def rowcount():
    s, b, raw = safe_request("POST", "collections/get_stats", {"collectionName": CLS})
    rc = ((b or {}).get("data") or {}).get("rowCount")
    return rc, raw

def verdict(v):
    print(f"VERDICT: {v}"); sys.exit(1 if v == "DEFECT_FOUND" else (2 if v == "SCRIPT_ERROR" else 0))

try:
    safe_request("POST", "collections/drop", {"collectionName": CLS})
    s, b, raw = safe_request("POST", "collections/create", {"collectionName": CLS, "dimension": DIM})
    if not ok(b): print(raw); verdict("SCRIPT_ERROR")
    safe_request("POST", "collections/load", {"collectionName": CLS})
    time.sleep(3)

    # Phase 1: insert 20 rows in 4 batches -> flush -> rowCount must be 20
    n = 0
    for batch in range(4):
        data = [{"id": batch*5+i+1, "vector": [0.1]*DIM} for i in range(5)]
        s, b, raw = safe_request("POST", "entities/insert", {"collectionName": CLS, "data": data})
        print(f"insert batch {batch}: {raw[:100]}")
        if ok(b): n += ((b.get("data") or {}).get("insertCount") or 0)
    if n != 20: print(f"setup inserted {n} != 20"); verdict("SCRIPT_ERROR")
    s, b, raw = safe_request("POST", "collections/flush", {"collectionName": CLS})
    print(f"flush: {raw[:100]}")
    time.sleep(3)
    rc, raw = rowcount(); print(f"rowCount after 20 inserts+flush: {raw[:120]}")
    if rc != 20:
        print(f"DEFECT: rowCount={rc} expected 20"); verdict("DEFECT_FOUND")

    # Phase 2: upsert same ids must NOT change count (upsert atomic invariant)
    up_data = [{"id": i, "vector": [0.2]*DIM} for i in range(1, 6)]
    s, b, raw = safe_request("POST", "entities/upsert", {"collectionName": CLS, "data": up_data})
    print(f"upsert 5 existing ids: {raw[:120]}")
    safe_request("POST", "collections/flush", {"collectionName": CLS}); time.sleep(3)
    rc, raw = rowcount(); print(f"rowCount after upsert-existing: {raw[:120]}")
    if rc != 20:
        print(f"DEFECT: upsert on existing pks changed rowCount {rc} != 20"); verdict("DEFECT_FOUND")

    # Phase 3: delete 5 -> count 15 (pre-compaction 20 tolerated, flag absurd values)
    s, b, raw = safe_request("POST", "entities/delete",
        {"collectionName": CLS, "filter": "id in [1,2,3,4,5]"})
    print(f"delete 5: {raw[:120]}")
    if not ok(b): verdict("SCRIPT_ERROR")
    time.sleep(3)
    rc, raw = rowcount(); print(f"rowCount after delete 5: {raw[:120]}")
    if rc not in (15, 20):
        print(f"DEFECT: rowCount={rc} after deleting 5 of 20 (expected 15, at most 20)"); verdict("DEFECT_FOUND")
    if rc == 20:
        print("NOTE: deleted rows still counted pre-compaction")

    # get on deleted id must return empty data (not error), even at code 0
    s, b, raw = safe_request("POST", "entities/get", {"collectionName": CLS, "id": 1})
    print(f"get deleted id=1: {raw[:150]}")
    if ok(b) and (b.get("data") or []):
        print("DEFECT: deleted id=1 still returned by entities/get"); verdict("DEFECT_FOUND")

    verdict("NO_DEFECT")
finally:
    try: safe_request("POST", "collections/drop", {"collectionName": CLS})
    except Exception: pass
