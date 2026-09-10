# state_partialupdate_concurrent_07.py
# Attack: entities+upsert partialUpdate (2.6 new) — idempotence + concurrent partial upserts on same pk
# Covers: entities+upsert(partialUpdate) / entities+get / entities+insert
# Invariants: milvus_inv_upsert_atomic_001; partial update must not zero out untouched fields
# Blindspot: BS-03 Concurrency Blindness
import os, sys, time, threading, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
BASE_URL = BASE_URL.rstrip("/")
H = {"Content-Type": "application/json", "Authorization": "Bearer root:Milvus"}
CLS = "stt_pupd_07"; DIM = 4

def safe_request(method, path, payload=None):
    try:
        r = requests.request(method, f"{BASE_URL}/v2/vectordb/{path}", headers=H, json=payload or {}, timeout=60)
        try: body = r.json()
        except Exception: body = None
        return r.status_code, body, r.text
    except Exception as e:
        return -1, None, f"EXC:{e}"

def ok(b): return b is not None and b.get("code") == 0

def get_row(pid):
    s, b, raw = safe_request("POST", "entities/get",
        {"collectionName": CLS, "id": pid, "outputFields": ["*"]})
    if not ok(b): return None, raw
    data = b.get("data") or []
    return (data[0] if data else None), raw

def verdict(v):
    print(f"VERDICT: {v}"); sys.exit(1 if v == "DEFECT_FOUND" else (2 if v == "SCRIPT_ERROR" else 0))

try:
    safe_request("POST", "collections/drop", {"collectionName": CLS})
    s, b, raw = safe_request("POST", "collections/create", {"collectionName": CLS, "dimension": DIM})
    if not ok(b): print(raw); verdict("SCRIPT_ERROR")
    safe_request("POST", "collections/load", {"collectionName": CLS}); time.sleep(3)

    # schema: add nullable scalar fields a, b for partial update test
    for f in ("pa", "pb"):
        s, b, raw = safe_request("POST", "collections/fields/add",
            {"collectionName": CLS, "schema": {"fieldName": f, "dataType": "Int64", "nullable": True}})
        if not ok(b): print(f"fields+add {f}: {raw}"); verdict("SCRIPT_ERROR")

    # base row
    s, b, raw = safe_request("POST", "entities/insert",
        {"collectionName": CLS, "data": [{"id": 1, "vector": [0.1]*DIM, "pa": 10, "pb": 20}]})
    if not ok(b): print(raw); verdict("SCRIPT_ERROR")

    # 1. partialUpdate touching only pa; pb must stay 20, vector must stay
    s, b, raw = safe_request("POST", "entities/upsert",
        {"collectionName": CLS, "partialUpdate": True,
         "data": [{"id": 1, "pa": 11}]})
    print(f"partial upsert pa=11: {raw[:150]}")
    if not ok(b):
        print(f"NOTE: partial upsert rejected code={(b or {}).get('code')} msg={(b or {}).get('message','')[:150]}")
    else:
        time.sleep(1)
        row, raw = get_row(1)
        print(f"row after partial: {raw[:250]}")
        if row is None or row.get("pa") != 11:
            print(f"DEFECT: pa={row and row.get('pa')} expected 11"); verdict("DEFECT_FOUND")
        if row.get("pb") != 20:
            print(f"DEFECT: partial update clobbered pb={row.get('pb')} expected 20"); verdict("DEFECT_FOUND")
        if not row.get("vector"):
            print("DEFECT: partial update clobbered vector"); verdict("DEFECT_FOUND")

    # 2. idempotence: same partial upsert twice -> count stays 1, pa stays 11
    for _ in range(2):
        safe_request("POST", "entities/upsert",
            {"collectionName": CLS, "partialUpdate": True, "data": [{"id": 1, "pa": 11}]})
    time.sleep(1)
    s, b, raw = safe_request("POST", "entities/query",
        {"collectionName": CLS, "filter": "id == 1", "limit": 10})
    rows = (b or {}).get("data") or []
    if len(rows) != 1:
        print(f"DEFECT: id==1 returned {len(rows)} rows after repeated upserts"); verdict("DEFECT_FOUND")

    # 3. concurrent partial upserts on same pk: one touches pa, other pb
    errs = []
    def worker(field, val, n):
        for i in range(n):
            s, b, raw = safe_request("POST", "entities/upsert",
                {"collectionName": CLS, "partialUpdate": True, "data": [{"id": 2, field: val}]})
            if not ok(b):
                errs.append((field, (b or {}).get("code"), ((b or {}).get("message") or "")[:100]))
    s, b, raw = safe_request("POST", "entities/insert",
        {"collectionName": CLS, "data": [{"id": 2, "vector": [0.2]*DIM, "pa": 1, "pb": 2}]})
    if not ok(b): print(raw); verdict("SCRIPT_ERROR")
    t1 = threading.Thread(target=worker, args=("pa", 111, 8))
    t2 = threading.Thread(target=worker, args=("pb", 222, 8))
    t1.start(); t2.start(); t1.join(); t2.join()
    print(f"concurrent partial upserts errors: {len(errs)}"); [print(f"  {e}") for e in errs[:5]]
    time.sleep(2)
    row, raw = get_row(2)
    print(f"row id=2 after race: {raw[:250]}")
    if row is None:
        print("DEFECT: row id=2 vanished after concurrent partial upserts"); verdict("DEFECT_FOUND")
    if row.get("pa") != 111 or row.get("pb") != 222:
        print(f"DEFECT: lost update in concurrent partial upserts: pa={row.get('pa')} pb={row.get('pb')} (expected 111/222)")
        verdict("DEFECT_FOUND")
    if errs and all(c in (0, 2, 65535) for _, c, _ in errs) is False:
        pass  # error codes recorded; judge by data outcome above

    verdict("NO_DEFECT")
finally:
    try: safe_request("POST", "collections/drop", {"collectionName": CLS})
    except Exception: pass
