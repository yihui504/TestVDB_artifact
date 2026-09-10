# Attack: error envelope consistency (milvus_bc_error_envelope) x 4 endpoints
# Blindspot: BS-02/BS-05; contract milvus_bc_error_envelope + milvus_behavioral_describe_001
# + milvus_behavioral_drop_001 + milvus_behavioral_load_state_001
# source: https://github.com/milvus-io/milvus/blob/v2.3.22/pkg/util/merr/errors.go  doc_version v2.3.22
import os, sys, json, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set"); sys.exit(2)
H = {"Content-Type": "application/json", "Authorization": "Bearer root:Milvus"}

def safe_request(method, endpoint, json=None, timeout=15):
    try:
        r = requests.request(method, f"{BASE_URL}{endpoint}", json=json, headers=H, timeout=timeout)
        try: body = r.json()
        except Exception: body = r.text
        return r.status_code, body, r.text
    except Exception as e:
        return -1, str(e), str(e)

MISSING = "testvdb_missing_coll_9x"

# 1. v1 describe (GET) not-found
s1, b1, r1 = safe_request("GET", f"/v1/vector/collections/describe?collectionName={MISSING}")
print("v1_describe:", s1, r1[:200])
# 2. v1 drop not-found
s2, b2, r2 = safe_request("POST", "/v1/vector/collections/drop", json={"collectionName": MISSING})
print("v1_drop:", s2, r2[:200])
# 3. v2 describe not-found
s3, b3, r3 = safe_request("POST", "/v2/vectordb/collections/describe", json={"collectionName": MISSING})
print("v2_describe:", s3, r3[:200])
# 4. v2 get_load_state not-found
s4, b4, r4 = safe_request("POST", "/v2/vectordb/collections/get_load_state", json={"collectionName": MISSING})
print("v2_load_state:", s4, r4[:200])

def code_of(b):
    return b.get("code") if isinstance(b, dict) else None

codes = [code_of(b) for b in (b1, b2, b3, b4)]
statuses = [s1, s2, s3, s4]
print("codes:", codes, "http:", statuses)

defects = []
# Envelope: business errors must be HTTP 200 + nonzero code
for name, s, c in zip(("v1_describe","v1_drop","v2_describe","v2_load_state"), statuses, codes):
    if s != 200:
        defects.append(f"{name}: HTTP {s} violates envelope (expected 200)")
    elif not isinstance(c, int) or c == 200:
        defects.append(f"{name}: not-found returned success code {c} (Type1_IllegalSuccess)")
# Consistency: same semantic error (collection not found) -> same code across endpoints
if len(set(codes)) > 1:
    defects.append(f"same not-found error maps to inconsistent codes {codes} (Type2_PoorDiagnostics)")
# Code 100 expected per contract
for name, c in zip(("v1_describe","v1_drop","v2_describe","v2_load_state"), codes):
    if isinstance(c, int) and c not in (100, 1100, 1000):
        defects.append(f"{name}: expected code 100, got {c}")

if defects:
    print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics / Type1_IllegalSuccess)")
    for d in defects: print("-", d)
    sys.exit(1)
print("VERDICT: NO_DEFECT")
