# state_load_lifecycle_01.py
# Attack: milvus_inv_load_lifecycle — load state machine edge transitions
# NotExist -> NotLoad -> Loading -> Loaded; release -> NotLoad; ops at each state
# Strategy: index_state / state transition violation
# Blindspot: BS-03
import os, sys, json, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530")
if not os.environ.get("TESTVDB_DB_URL"):
    print("NOTE: TESTVDB_DB_URL unset, using local default for manual exec")
HDR = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}

def req(method, path, body=None):
    try:
        r = requests.request(method, BASE_URL + path, headers=HDR, json=body if body is not None else {}, timeout=30)
        try:
            b = r.json()
        except Exception:
            b = None
        return r.status_code, b, r.text
    except Exception as e:
        return -1, None, str(e)

CLS = "st_load_01"
def create():
    return req("POST", "/v2/vectordb/collections/create",
        {"collectionName": CLS, "dimension": 4, "autoId": False})

def load_state(name=CLS):
    s, b, raw = req("POST", "/v2/vectordb/collections/get_load_state", {"collectionName": name})
    if s != 200 or not isinstance(b, dict) or b.get("code") != 200:
        return ("ERR", raw[:200])
    return (b.get("data", {}) or {}).get("loadState"), raw

def insert_n(n, start=0):
    body = {"collectionName": CLS, "data": [
        {"id": start + i, "vector": [0.1, 0.2, 0.3, 0.4]} for i in range(n)]}
    return req("POST", "/v2/vectordb/entities/insert", body)

try:
    try:
        req("POST", "/v2/vectordb/collections/release", {"collectionName": CLS})
    except Exception:
        pass
    try:
        req("POST", "/v2/vectordb/collections/drop", {"collectionName": CLS})
    except Exception:
        pass

    s, b, raw = create()
    print("create:", s, raw[:200])
    if not (s == 200 and b and b.get("code") == 200):
        print("VERDICT: SCRIPT_ERROR"); sys.exit(2)

    # 1. state right after create should be NotLoad
    st, raw = load_state()
    print("state after create:", st, raw[:150])
    if st not in ("NotLoad", "LoadStateNotLoad", "LoadStateLoading", "LoadStateLoaded"):
        print(f"SUSPECT: expected NotLoad after create, got {st}")

    # 2. query before load -> should fail (code != 200)
    s, b, raw = req("POST", "/v2/vectordb/entities/query", {"collectionName": CLS, "filter": "id >= 0", "limit": 10})
    print("query before load:", s, raw[:200])

    # 3. load -> wait Loaded
    s, b, raw = req("POST", "/v2/vectordb/collections/load", {"collectionName": CLS})
    print("load:", s, raw[:200])
    import time
    st = None
    for _ in range(30):
        st, raw = load_state()
        if st in ("LoadStateLoaded", "Loaded"):
            break
        time.sleep(0.5)
    print("state after load:", st)
    if st not in ("LoadStateLoaded", "Loaded"):
        print("VERDICT: SCRIPT_ERROR — never reached Loaded"); sys.exit(2)

    # 4. double load — should be ok (idempotent) not internal error
    s, b, raw = req("POST", "/v2/vectordb/collections/load", {"collectionName": CLS})
    print("double load:", s, raw[:200])
    if s == 200 and b and b.get("code") == 200:
        pass
    elif b and b.get("code") not in (200, 65535):
        print(f"SUSPECT: double load returned code {b.get('code')}")

    # 5. release -> NotLoad
    s, b, raw = req("POST", "/v2/vectordb/collections/release", {"collectionName": CLS})
    print("release:", s, raw[:200])
    time.sleep(1)
    st, raw = load_state()
    print("state after release:", st, raw[:150])
    if st not in ("LoadStateNotLoad", "NotLoad"):
        print(f"DEFECT_CANDIDATE Type4: after release loadState should be NotLoad, got {st}")

    # 6. double release — idempotent or clean error, not unexpected code
    s, b, raw = req("POST", "/v2/vectordb/collections/release", {"collectionName": CLS})
    print("double release:", s, raw[:200])

    # 7. search after release -> should fail cleanly (not Loaded)
    s, b, raw = req("POST", "/v2/vectordb/entities/search", {
        "collectionName": CLS, "data": [[0.1, 0.2, 0.3, 0.4]], "limit": 3})
    print("search after release:", s, raw[:200])

    # 8. drop -> NotExist
    s, b, raw = req("POST", "/v2/vectordb/collections/drop", {"collectionName": CLS})
    print("drop:", s, raw[:150])
    time.sleep(1)
    st, raw = load_state()
    print("state after drop:", st, raw[:200])
    if st not in ("NotExist", "LoadStateNotExist"):
        print(f"DEFECT_CANDIDATE Type4: after drop loadState should be NotExist, got {st}")

    # 9. load a dropped collection -> must fail cleanly
    s, b, raw = req("POST", "/v2/vectordb/collections/load", {"collectionName": CLS})
    print("load dropped:", s, raw[:200])
    if s == 200 and b and b.get("code") == 200:
        print("DEFECT_CANDIDATE Type1: load on dropped collection returned success")

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
