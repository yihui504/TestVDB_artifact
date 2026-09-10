# state_drop_recreate_04.py
# Attack: drop+recreate same name & alias rebinding state residue
# - recreate with different schema -> old data must not leak, load state resets
# - alias points to A; drop A; alias state; alter alias to B
# Strategy: lifecycle (delete_consistency). invariant: milvus_inv_dropped_absent.
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

A, B, AL = "st_dr_a04", "st_dr_b04", "st_dr_al04"

def create(name, dim=4):
    return req("POST", "/v2/vectordb/collections/create",
        {"collectionName": name, "dimension": dim, "autoId": False})

def rowcount(name):
    s, b, raw = req("POST", "/v2/vectordb/collections/get_stats", {"collectionName": name})
    if not (s == 200 and b and b.get("code") == 200):
        return None, raw[:150]
    return int((b.get("data") or {}).get("rowCount", -1)), raw

def drop(name):
    try:
        req("POST", "/v2/vectordb/collections/drop", {"collectionName": name})
    except Exception:
        pass

try:
    for n in (A, B):
        drop(n)
    try:
        req("POST", "/v2/vectordb/aliases/drop", {"aliasName": AL})
    except Exception:
        pass

    s, b, raw = create(A, 4)
    print("create A:", s, raw[:150])
    req("POST", "/v2/vectordb/collections/load", {"collectionName": A})
    time.sleep(2)
    s, b, raw = req("POST", "/v2/vectordb/entities/insert", {"collectionName": A, "data": [
        {"id": i, "vector": [0.1, 0.2, 0.3, 0.4]} for i in range(5)]})
    print("insert 5 into A:", s, raw[:150])
    time.sleep(2)

    # drop A then recreate same name with dim 8
    drop(A); time.sleep(1)
    s, b, raw = req("POST", "/v2/vectordb/collections/describe", {"collectionName": A})
    print("describe dropped A:", s, raw[:200])
    code = (b or {}).get("code")
    if code == 200:
        print("DEFECT_CANDIDATE Type1: describe after drop returned code 200")

    s, b, raw = create(A, 8)
    print("recreate A dim=8:", s, raw[:200])
    time.sleep(1)
    rc, raw = rowcount(A)
    print("rowCount of recreated A:", rc, raw[:150])
    if rc not in (0, None) and rc > 0:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — recreated collection retained {rc} old rows")
        sys.exit(1)

    # alias lifecycle: create alias -> A, drop A, inspect alias, alter -> B
    s, b, raw = req("POST", "/v2/vectordb/aliases/create", {"collectionName": A, "aliasName": AL})
    print("alias create -> A:", s, raw[:150])
    drop(A); time.sleep(1)
    s, b, raw = req("POST", "/v2/vectordb/aliases/describe", {"aliasName": AL})
    print("alias describe after target dropped:", s, raw[:250])

    s, b, raw = create(B, 4)
    print("create B:", s, raw[:150])
    s, b, raw = req("POST", "/v2/vectordb/aliases/alter", {"collectionName": B, "aliasName": AL})
    print("alias alter -> B:", s, raw[:200])
    s, b, raw = req("POST", "/v2/vectordb/collections/has", {"collectionName": AL})
    print("has via alias:", s, raw[:150])
    if s == 200 and b and b.get("code") == 200 and (b.get("data") or {}).get("has") is not True:
        print("DEFECT_CANDIDATE: alias not resolvable after alter")

    print("VERDICT: NO_DEFECT")
    sys.exit(0)
except Exception as e:
    print("EXC:", e)
    print("VERDICT: SCRIPT_ERROR")
    sys.exit(2)
finally:
    for n in (A, B):
        drop(n)
    try:
        req("POST", "/v2/vectordb/aliases/drop", {"aliasName": AL})
    except Exception:
        pass
