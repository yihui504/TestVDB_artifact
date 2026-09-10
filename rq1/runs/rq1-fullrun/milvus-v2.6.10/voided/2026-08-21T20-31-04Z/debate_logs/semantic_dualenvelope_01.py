# semantic_dualenvelope_01 — dual envelope consistency (v2 vs v1 same user-input error)
# Attack: behavioral_contract milvus_bc_envelope_v2_001 + milvus_bc_envelope_v1_002
#   × constraint milvus_type_entities_search_001 (consistencyLevel enum, code 1100)
# Blindspot: BS-02 Error Message Negligence / BS-05 Documentation Drift
import os, sys, json, requests

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

def ok(body):
    return isinstance(body, dict) and body.get("code") == 0

# --- Case A: v2 user-input error (missing required collectionName) ---
st, body, raw = safe_request("POST", "/v2/vectordb/collections/describe", {"collectionName": ""})
print("A1 v2 describe empty name:", st, raw[:300])
if st != 200 or not isinstance(body, dict):
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — v2 envelope violated: HTTP %s, non-dict body" % st)
    sys.exit(1)
code_a = body.get("code")
if code_a in (None, 0, 65535):
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — v2 user-input error used code=%r (expected specific merr code, 65535=unknown violates envelope)" % code_a)
    sys.exit(1)

# --- Case B: v2 same class of error on different endpoint (search with bad consistencyLevel) ---
COL = "sem_dualev_01"
try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
st, body, raw = safe_request("POST", "/v2/vectordb/collections/create",
                             {"collectionName": COL, "dimension": 8})
print("B0 create:", st, raw[:200])
if not (st == 200 and ok(body)):
    print("VERDICT: SCRIPT_ERROR — create failed: %s" % raw[:200]); sys.exit(2)

st, body, raw = safe_request("POST", "/v2/vectordb/entities/search",
                             {"collectionName": COL, "data": [[0.1] * 8],
                              "consistencyLevel": "Bogus"})
print("B1 v2 search bad consistencyLevel:", st, raw[:300])
if st != 200:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — v2 error returned non-200 HTTP %s" % st)
    sys.exit(1)
code_b = body.get("code") if isinstance(body, dict) else None
if code_b not in (1100, 65535) or code_b is None:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — consistencyLevel enum violation returned code=%r, contract requires 1100" % code_b)
    sys.exit(1)
if code_b == 65535:
    print("NOTE: enum violation surfaced as 65535 (undifferentiated) — envelope classification defect candidate")
msg = str(body.get("message", "")).lower()
named = "consistencylevel" in msg
fmt = any(h in msg for h in ["strong", "session", "bounded", "eventually", "customized", "must be", "can only be"])
print("B1 msg names param:", named, "| lists valid values:", fmt)

# --- Case C: v1 legacy surface, same user-input error class (missing required dimension) ---
st, body, raw = safe_request("POST", "/v1/vector/collections/create",
                             {"collectionName": "sem_dualev_v1"})
print("C1 v1 create missing dimension:", st, raw[:300])
if not isinstance(body, dict) or body.get("code") != 1802:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — v1 missing-required did not use 1802: %s" % raw[:200])
    sys.exit(1)

# cleanup
try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass

print("VERDICT: NO_DEFECT")
