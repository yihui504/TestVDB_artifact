# state_fieldadd_data_04.py
# Attack: collections+fields+add dynamic schema vs existing-data consistency (2.6 new state surface)
# Covers: collections+fields+add / entities+insert / entities+get / entities+query / collections+refresh_load
# Focus: nullable enforcement; old rows new field null; non-nullable add must be rejected (code!=0);
#        insert with missing new nullable field must succeed; get must show nf:null for old rows.
import os, sys, time, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
BASE_URL = BASE_URL.rstrip("/")
H = {"Content-Type": "application/json", "Authorization": "Bearer root:Milvus"}
CLS = "stt_fadd_04"; DIM = 4

def safe_request(method, path, payload=None):
    try:
        r = requests.request(method, f"{BASE_URL}/v2/vectordb/{path}", headers=H, json=payload or {}, timeout=60)
        try: body = r.json()
        except Exception: body = None
        return r.status_code, body, r.text
    except Exception as e:
        return -1, None, f"EXC:{e}"

def ok(b): return b is not None and b.get("code") == 0

def verdict(v):
    print(f"VERDICT: {v}"); sys.exit(1 if v == "DEFECT_FOUND" else (2 if v == "SCRIPT_ERROR" else 0))

try:
    safe_request("POST", "collections/drop", {"collectionName": CLS})
    s, b, raw = safe_request("POST", "collections/create", {"collectionName": CLS, "dimension": DIM})
    if not ok(b): print(raw); verdict("SCRIPT_ERROR")
    safe_request("POST", "collections/load", {"collectionName": CLS}); time.sleep(3)

    # old row without nf
    s, b, raw = safe_request("POST", "entities/insert",
        {"collectionName": CLS, "data": [{"id": 1, "vector": [0.1]*DIM}]})
    print(f"insert old row: {raw[:100]}")
    if not ok(b): verdict("SCRIPT_ERROR")

    # 1. add NON-nullable field must be rejected (server must enforce nullable for added fields)
    s, b, raw = safe_request("POST", "collections/fields/add",
        {"collectionName": CLS, "schema": {"fieldName": "bad_nf", "dataType": "Int64"}})
    print(f"fields+add non-nullable: {raw[:200]}")
    if ok(b):
        print("DEFECT: non-nullable field add accepted (existing rows cannot backfill)")
        verdict("DEFECT_FOUND")

    # 2. add nullable field -> schema must contain it with nullable true
    s, b, raw = safe_request("POST", "collections/fields/add",
        {"collectionName": CLS, "schema": {"fieldName": "nf", "dataType": "Int64", "nullable": True}})
    print(f"fields+add nullable nf: {raw[:150]}")
    if not ok(b): verdict("SCRIPT_ERROR")
    s, b, raw = safe_request("POST", "collections/describe", {"collectionName": CLS})
    fields = ((b or {}).get("data") or {}).get("fields") or []
    names = {f.get("name"): f.get("nullable") for f in fields}
    print(f"schema fields: {names}")
    if "nf" not in names or names.get("nf") is not True:
        print("DEFECT: added field nf missing or not nullable in schema"); verdict("DEFECT_FOUND")
    if "bad_nf" in names:
        print("DEFECT: rejected non-nullable field bad_nf leaked into schema"); verdict("DEFECT_FOUND")

    # 3. insert new row WITH nf and old-style row WITHOUT nf -> both must succeed
    s, b, raw = safe_request("POST", "entities/insert",
        {"collectionName": CLS, "data": [{"id": 2, "vector": [0.2]*DIM, "nf": 9},
                                          {"id": 3, "vector": [0.3]*DIM}]})
    print(f"insert with/without nf: {raw[:150]}")
    if not ok(b):
        print("DEFECT: insert of row missing optional nullable field rejected"); verdict("DEFECT_FOUND")

    # 4. refresh_load then get old row: nf must be null (not absent, not error)
    safe_request("POST", "collections/refresh_load", {"collectionName": CLS}); time.sleep(2)
    s, b, raw = safe_request("POST", "entities/get",
        {"collectionName": CLS, "id": 1, "outputFields": ["*"]})
    print(f"get old row id=1: {raw[:250]}")
    if not ok(b):
        code = (b or {}).get("code")
        print(f"DEFECT: get old row after fields+add failed code={code}"); verdict("DEFECT_FOUND")
    row = ((b.get("data") or [None])[0]) or {}
    if "nf" not in row:
        print("DEFECT: nf field missing from old row output with outputFields=*"); verdict("DEFECT_FOUND")
    if row.get("nf") is not None:
        print(f"DEFECT: old row nf={row.get('nf')} expected null"); verdict("DEFECT_FOUND")

    # 5. query filter on new field: nf == 9 must return only id=2
    s, b, raw = safe_request("POST", "entities/query",
        {"collectionName": CLS, "filter": "nf == 9", "outputFields": ["id", "nf"], "limit": 10})
    print(f"query nf==9: {raw[:250]}")
    if not ok(b):
        print("DEFECT: query on newly added field failed"); verdict("DEFECT_FOUND")
    rows = b.get("data") or []
    if len(rows) != 1 or (rows[0] or {}).get("id") != 2:
        print(f"DEFECT: nf==9 returned {rows}"); verdict("DEFECT_FOUND")

    verdict("NO_DEFECT")
finally:
    try: safe_request("POST", "collections/drop", {"collectionName": CLS})
    except Exception: pass
