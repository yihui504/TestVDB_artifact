# state_drop_recreate_05.py
# Attack: drop -> recreate same name state residue + alias rebind residue
# Covers: collections+drop / collections+create / collections+has / aliases+create / aliases+alter / aliases+drop / entities+insert / entities+query
# Invariants: milvus_inv_dropped_absent_001, milvus_inv_created_visible_001
import os, sys, time, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
BASE_URL = BASE_URL.rstrip("/")
H = {"Content-Type": "application/json", "Authorization": "Bearer root:Milvus"}
CLS = "stt_recr_05"; ALIAS = "stt_recr_05_alias"; DIM = 4

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

def drop(name):
    try: safe_request("POST", "collections/drop", {"collectionName": name})
    except Exception: pass

try:
    drop(CLS)
    # --- A. drop-recreate data isolation ---
    s, b, raw = safe_request("POST", "collections/create", {"collectionName": CLS, "dimension": DIM})
    if not ok(b): print(raw); verdict("SCRIPT_ERROR")
    safe_request("POST", "collections/load", {"collectionName": CLS}); time.sleep(2)
    safe_request("POST", "entities/insert", {"collectionName": CLS, "data": [{"id": 1, "vector": [0.1]*DIM}]})
    safe_request("POST", "collections/flush", {"collectionName": CLS})

    # alias bound to CLS
    s, b, raw = safe_request("POST", "aliases/create", {"collectionName": CLS, "aliasName": ALIAS})
    print(f"alias create: {raw[:120]}")

    defect_flag = False
    s, b, raw = safe_request("POST", "collections/drop", {"collectionName": CLS})
    print(f"drop: {raw[:200]}")
    if not ok(b):
        code = (b or {}).get("code")
        msg = (b or {}).get("message") or ""
        if code == 65535 and "associated aliases" in msg:
            print("DEFECT: collections+drop blocked by alias association -> generic 65535 UnexpectedError;")
            print("  contract describes drop as atomic with no alias prerequisite; expected 1xxx specific code")
            defect_flag = True
            safe_request("POST", "aliases/drop", {"aliasName": ALIAS})
            s, b, raw = safe_request("POST", "collections/drop", {"collectionName": CLS})
            print(f"drop after alias removal: {raw[:120]}")
            if not ok(b): verdict("SCRIPT_ERROR")
        else:
            verdict("SCRIPT_ERROR")

    # invariant: dropped -> has=false, describe code 100
    s, b, raw = safe_request("POST", "collections/has", {"collectionName": CLS})
    print(f"has after drop: {raw[:120]}")
    if ((b or {}).get("data") or {}).get("has") is not False:
        print("DEFECT: has!=false after drop (milvus_inv_dropped_absent_001)"); verdict("DEFECT_FOUND")
    s, b, raw = safe_request("POST", "collections/describe", {"collectionName": CLS})
    code = (b or {}).get("code")
    print(f"describe after drop: code={code}")
    if code != 100:
        print(f"DEFECT: describe after drop code={code} expected 100"); verdict("DEFECT_FOUND")

    # alias must not resolve to dropped collection
    s, b, raw = safe_request("POST", "entities/query",
        {"collectionName": ALIAS, "filter": "id >= 0", "limit": 1})
    print(f"query via alias of dropped: {raw[:200]}")
    if ok(b):
        print("DEFECT: query via alias succeeded after target dropped (stale alias state)"); verdict("DEFECT_FOUND")

    # recreate same name: must be empty (no residue)
    s, b, raw = safe_request("POST", "collections/create", {"collectionName": CLS, "dimension": DIM})
    print(f"recreate: {raw[:120]}")
    if not ok(b):
        print("DEFECT: recreate after drop failed"); verdict("DEFECT_FOUND")
    safe_request("POST", "collections/load", {"collectionName": CLS}); time.sleep(3)
    safe_request("POST", "collections/flush", {"collectionName": CLS}); time.sleep(2)
    s, b, raw = safe_request("POST", "collections/get_stats", {"collectionName": CLS})
    print(f"stats after recreate: {raw[:120]}")
    rc = ((b or {}).get("data") or {}).get("rowCount")
    if rc not in (0, None):
        print(f"DEFECT: recreated collection rowCount={rc} (data residue from pre-drop)"); verdict("DEFECT_FOUND")

    # --- B. alias rebind: old target must be unreachable via alias ---
    CLS2 = CLS + "_b"
    drop(CLS2)
    s, b, raw = safe_request("POST", "collections/create", {"collectionName": CLS2, "dimension": DIM})
    if not ok(b): verdict("SCRIPT_ERROR")
    safe_request("POST", "collections/load", {"collectionName": CLS2}); time.sleep(2)
    safe_request("POST", "entities/insert",
        {"collectionName": CLS2, "data": [{"id": 100, "vector": [0.9]*DIM}]})
    safe_request("POST", "collections/flush", {"collectionName": CLS2}); time.sleep(2)

    safe_request("POST", "aliases/create", {"collectionName": CLS, "aliasName": ALIAS})
    s, b, raw = safe_request("POST", "aliases/alter", {"collectionName": CLS2, "aliasName": ALIAS})
    print(f"alias alter -> CLS2: {raw[:120]}")
    if not ok(b): verdict("SCRIPT_ERROR")
    s, b, raw = safe_request("POST", "aliases/describe", {"aliasName": ALIAS})
    print(f"alias describe: {raw[:200]}")

    # query via alias must see CLS2 data, never CLS data (CLS is empty anyway after recreate)
    s, b, raw = safe_request("POST", "entities/query",
        {"collectionName": ALIAS, "filter": "id >= 0", "outputFields": ["id"], "limit": 10,
         "consistencyLevel": "Strong"})
    print(f"query via rebound alias: {raw[:250]}")
    if not ok(b): verdict("SCRIPT_ERROR")
    ids = [r.get("id") for r in (b.get("data") or [])]
    if ids != [100]:
        print(f"DEFECT: alias rebind residue: ids={ids} expected [100]"); verdict("DEFECT_FOUND")

    # drop alias-bound target: server blocks drop (alias association) -> record behavior.
    # Only if drop actually SUCCEEDS does the alias-residue assertion apply.
    s, b, raw = safe_request("POST", "collections/drop", {"collectionName": CLS2})
    print(f"drop alias-bound target2: {raw[:200]}")
    if ok(b):
        time.sleep(2)
        s2, b2, raw2 = safe_request("POST", "entities/query",
            {"collectionName": ALIAS, "filter": "id >= 0", "limit": 1})
        print(f"query via alias of dropped target2: {raw2[:200]}")
        code = (b2 or {}).get("code")
        if code == 0:
            print("DEFECT: alias query succeeded on dropped target"); verdict("DEFECT_FOUND")
        if code == 65535:
            print("DEFECT: alias-of-dropped query returns generic 65535, expected 100"); verdict("DEFECT_FOUND")
    else:
        c2 = (b or {}).get("code")
        if c2 == 65535:
            print("DEFECT(2nd): alias-bound drop -> generic 65535 (same defect class as phase A)")
            defect_flag = True
        else:
            print(f"NOTE: alias-bound drop rejected with specific code {c2} (by-design prerequisite)")

    verdict("DEFECT_FOUND" if defect_flag else "NO_DEFECT")
finally:
    for n in (CLS, CLS + "_b"):
        drop(n)
    try: safe_request("POST", "aliases/drop", {"aliasName": ALIAS})
    except Exception: pass
