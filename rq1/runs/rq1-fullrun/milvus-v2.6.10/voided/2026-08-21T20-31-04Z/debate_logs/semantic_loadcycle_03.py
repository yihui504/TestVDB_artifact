# semantic_loadcycle_03 — load/release state machine codes (101 not loaded, 104 already loaded)
# Attack: behavioral_contract milvus_bc_load_release_001 × collections+load/release + entities+search
import os, sys, time, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set"); sys.exit(2)
AUTH = {"Content-Type": "application/json",
        "Authorization": "Bearer " + os.environ.get("TESTVDB_MILVUS_TOKEN", "root:Milvus")}

def safe_request(method, endpoint, json_body=None, timeout=15):
    try:
        r = requests.request(method, BASE_URL + endpoint, json=json_body, headers=AUTH, timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = r.text
        return r.status_code, body, r.text
    except Exception as e:
        return -1, str(e), str(e)

COL = "sem_load_03"
try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass

st, body, raw = safe_request("POST", "/v2/vectordb/collections/create",
                             {"collectionName": COL, "dimension": 8})
print("create:", st, raw[:200])
if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — create failed"); sys.exit(2)

def search_code():
    st, body, raw = safe_request("POST", "/v2/vectordb/entities/search",
                                 {"collectionName": COL, "data": [[0.0] * 8], "limit": 1})
    code = body.get("code") if isinstance(body, dict) else None
    return st, code, raw

# Phase 1: search before load -> expect code 101 (HTTP 200)
st, code, raw = search_code()
print("P1 search-not-loaded:", st, raw[:300])
if st != 200:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — not-loaded search gave HTTP %s (envelope violation)" % st); sys.exit(1)
if code != 101:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — search before load returned code=%r, contract expects 101" % code); sys.exit(1)

# Phase 2: load -> success; search -> code 0
st, body, raw = safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": COL})
print("P2 load:", st, raw[:200])
if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — load failed"); sys.exit(2)
time.sleep(2)
st, code, raw = search_code()
print("P2 search-loaded:", st, raw[:300])
if code != 0:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — search after load failed code=%r: %s" % (code, raw[:200])); sys.exit(1)

# Phase 3: load again on loaded -> expect code 104
st, body, raw = safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": COL})
print("P3 double load:", st, raw[:300])
code3 = body.get("code") if isinstance(body, dict) else None
if st != 200 or code3 is None:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — double load HTTP %s / no code" % st); sys.exit(1)
if code3 not in (0, 104):
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — double load returned code=%r, contract expects 104 (or documented idempotent 0)" % code3); sys.exit(1)

# Phase 4: release -> search -> code 101 again
st, body, raw = safe_request("POST", "/v2/vectordb/collections/release", {"collectionName": COL})
print("P4 release:", st, raw[:200])
if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — release failed"); sys.exit(2)
time.sleep(2)
st, code, raw = search_code()
print("P4 search-after-release:", st, raw[:300])
if code != 101:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — search after release returned code=%r, contract expects 101" % code); sys.exit(1)

try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
print("VERDICT: NO_DEFECT")
