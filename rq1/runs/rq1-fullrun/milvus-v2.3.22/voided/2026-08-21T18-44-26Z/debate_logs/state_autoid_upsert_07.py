# state_autoid_upsert_07.py
# Attack: milvus_inv_autoid_pk + drop-with-alias state residue.
# - autoId=true: explicit PK insert/upsert must fail (1804 for upsert); auto-generated PKs returned
# - collection with alias dropped -> alias/describe behavior
# Strategy: state machine / delete_consistency.
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

CLS, AL = "st_auto_07", "st_auto_al07"

def create(autoid):
    body = {"collectionName": CLS, "dimension": 4}
    if autoid is not None:
        body["autoId"] = autoid
    return req("POST", "/v2/vectordb/collections/create", body)

try:
    for n in (CLS,):
        try:
            req("POST", "/v2/vectordb/collections/drop", {"collectionName": n})
        except Exception:
            pass
    try:
        req("POST", "/v2/vectordb/aliases/drop", {"aliasName": AL})
    except Exception:
        pass

    s, b, raw = create(True)
    print("create autoId=true:", s, raw[:200])
    if not (s == 200 and b and b.get("code") == 200):
        print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
    req("POST", "/v2/vectordb/collections/load", {"collectionName": CLS})
    time.sleep(2)

    # explicit PK on autoId collection -> must be rejected
    s, b, raw = req("POST", "/v2/vectordb/entities/insert", {"collectionName": CLS, "data": [
        {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}]})
    print("insert explicit PK on autoId:", s, raw[:250])
    code = (b or {}).get("code")
    if code == 200:
        print("DEFECT_CANDIDATE Type1: explicit PK accepted on autoId=true collection")

    s, b, raw = req("POST", "/v2/vectordb/entities/upsert", {"collectionName": CLS, "data": [
        {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}]})
    print("upsert explicit PK on autoId:", s, raw[:250])
    code = (b or {}).get("code")
    if code == 200:
        print("DEFECT_CANDIDATE Type1: upsert with explicit PK accepted on autoId=true (expect 1804)")

    # valid autoId insert -> PKs returned
    s, b, raw = req("POST", "/v2/vectordb/entities/insert", {"collectionName": CLS, "data": [
        {"vector": [0.1, 0.2, 0.3, 0.4]} for _ in range(3)]})
    print("autoId insert:", s, raw[:250])

    # drop collection that has an alias
    s, b, raw = req("POST", "/v2/vectordb/aliases/create", {"collectionName": CLS, "aliasName": AL})
    print("alias create:", s, raw[:150])
    try:
        req("POST", "/v2/vectordb/collections/release", {"collectionName": CLS})
    except Exception:
        pass
    s, b, raw = req("POST", "/v2/vectordb/collections/drop", {"collectionName": CLS})
    print("drop aliased collection:", s, raw[:200])
    time.sleep(1)
    s, b, raw = req("POST", "/v2/vectordb/aliases/describe", {"aliasName": AL})
    print("alias describe after target dropped:", s, raw[:250])
    # recreate same collection name — does stale alias silently rebind?
    s, b, raw = create(False)
    print("recreate autoId=false:", s, raw[:150])
    time.sleep(1)
    s, b, raw = req("POST", "/v2/vectordb/aliases/describe", {"aliasName": AL})
    print("alias describe after recreate:", s, raw[:250])
    s, b, raw = req("POST", "/v2/vectordb/collections/has", {"collectionName": AL})
    print("has via stale alias after recreate:", s, raw[:200])
    bdata = (b or {}).get("data") or {}
    if bdata.get("has") is True:
        print("DEFECT_CANDIDATE Type4: stale alias auto-rebound to recreated collection")

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
    try:
        req("POST", "/v2/vectordb/aliases/drop", {"aliasName": AL})
    except Exception:
        pass
