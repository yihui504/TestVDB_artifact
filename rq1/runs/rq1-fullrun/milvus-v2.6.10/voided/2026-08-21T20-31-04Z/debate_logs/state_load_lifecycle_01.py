# state_load_lifecycle_01.py
# Attack: load/release/refresh_load state machine vs state_invariants (milvus v2.6.10 REST v2)
# Covers: collections+load / collections+release / collections+refresh_load / collections+get_load_state
# Focus: refresh_load on a released (NotLoad) collection returns generic 65535 UnexpectedError
#        instead of a precise not-loaded error code (101); release->load cycle must restore search.
# Blindspot: BS-03 Concurrency Blindness (lifecycle vs access)
import os, sys, time, json, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
BASE_URL = BASE_URL.rstrip("/")
H = {"Content-Type": "application/json", "Authorization": "Bearer root:Milvus"}
CLS = "stt_load_01"
DIM = 4

def safe_request(method, path, payload=None):
    url = f"{BASE_URL}/v2/vectordb/{path}"
    try:
        r = requests.request(method, url, headers=H, json=payload or {}, timeout=30)
        raw = r.text
        try:
            body = r.json()
        except Exception:
            body = None
        return r.status_code, body, raw
    except Exception as e:
        return -1, None, f"EXC:{e}"

def ok(body): return body is not None and body.get("code") == 0

def verdict(v):
    print(f"VERDICT: {v}"); sys.exit(1 if v == "DEFECT_FOUND" else (2 if v == "SCRIPT_ERROR" else 0))

try:
    # setup: clean + create
    safe_request("POST", "collections/drop", {"collectionName": CLS})
    s, b, raw = safe_request("POST", "collections/create", {"collectionName": CLS, "dimension": DIM})
    print(f"create: {raw[:150]}")
    if not ok(b): verdict("SCRIPT_ERROR")

    s, b, raw = safe_request("POST", "entities/insert",
        {"collectionName": CLS, "data": [{"id": 1, "vector": [0.1]*DIM}]})
    print(f"insert: {raw[:120]}")

    # 1. load -> state should eventually become LoadStateLoaded
    s, b, raw = safe_request("POST", "collections/load", {"collectionName": CLS})
    print(f"load: {raw[:120]}")
    if not ok(b): verdict("SCRIPT_ERROR")
    state = None
    for _ in range(30):
        s, b, raw = safe_request("POST", "collections/get_load_state", {"collectionName": CLS})
        state = (b or {}).get("data", {}).get("loadState")
        if state == "LoadStateLoaded": break
        time.sleep(1)
    print(f"load_state after load: {state}")
    if state != "LoadStateLoaded":
        print(f"DEFECT? load.code==0 but state never Loaded: {state}"); verdict("DEFECT_FOUND")

    # 2. refresh_load on a Loaded collection must succeed (code 0)
    s, b, raw = safe_request("POST", "collections/refresh_load", {"collectionName": CLS})
    print(f"refresh_load(loaded): {raw[:150]}")
    if not ok(b):
        print("DEFECT: refresh_load failed on Loaded collection"); verdict("DEFECT_FOUND")

    # 3. release -> state must be NotLoad; search must fail gracefully (code 101, not 65535)
    s, b, raw = safe_request("POST", "collections/release", {"collectionName": CLS})
    print(f"release: {raw[:120]}")
    time.sleep(2)
    s, b, raw = safe_request("POST", "collections/get_load_state", {"collectionName": CLS})
    print(f"load_state after release: {raw[:150]}")
    s, b, raw = safe_request("POST", "entities/search",
        {"collectionName": CLS, "data": [[0.1]*DIM], "limit": 1})
    print(f"search after release: {raw[:200]}")
    code = (b or {}).get("code")
    if code == 0:
        print("DEFECT: search succeeded on released collection"); verdict("DEFECT_FOUND")
    if code == 65535:
        print("DEFECT: search on released collection returns generic 65535, expected 101 NotLoaded")
        verdict("DEFECT_FOUND")

    # 4. refresh_load on released collection: expected graceful not-loaded error (101/100);
    #    generic 65535 UnexpectedError = state-machine handling defect
    s, b, raw = safe_request("POST", "collections/refresh_load", {"collectionName": CLS})
    print(f"refresh_load(released): {raw[:250]}")
    code = (b or {}).get("code")
    if code == 0:
        print("DEFECT: refresh_load.code==0 on NotLoad collection (no-op success is suspicious); checking state")
        s2, b2, _ = safe_request("POST", "collections/get_load_state", {"collectionName": CLS})
        print(f"state now: {(b2 or {}).get('data',{}).get('loadState')}")
    elif code == 65535:
        print("DEFECT: refresh_load on released collection -> 65535 UnexpectedError (generic), expected 101")
        verdict("DEFECT_FOUND")

    # 5. reload -> search must work again (state machine restores)
    safe_request("POST", "collections/load", {"collectionName": CLS})
    for _ in range(30):
        s, b, raw = safe_request("POST", "collections/get_load_state", {"collectionName": CLS})
        if (b or {}).get("data", {}).get("loadState") == "LoadStateLoaded": break
        time.sleep(1)
    s, b, raw = safe_request("POST", "entities/search",
        {"collectionName": CLS, "data": [[0.1]*DIM], "limit": 1})
    print(f"search after reload: {raw[:200]}")
    if not ok(b):
        print("DEFECT: search failed after load->release->load cycle"); verdict("DEFECT_FOUND")

    # 6. refresh_load on non-existent collection: must be code 100 not 65535
    s, b, raw = safe_request("POST", "collections/refresh_load", {"collectionName": CLS + "_nope"})
    print(f"refresh_load(nonexistent): {raw[:200]}")
    code = (b or {}).get("code")
    if code == 0:
        print("DEFECT: refresh_load succeeded on non-existent collection"); verdict("DEFECT_FOUND")
    if code == 65535:
        print("DEFECT: refresh_load on non-existent collection -> 65535 generic"); verdict("DEFECT_FOUND")

    verdict("NO_DEFECT")
finally:
    try: safe_request("POST", "collections/drop", {"collectionName": CLS})
    except Exception: pass
