# Attack: radius/range_filter coupling + metric direction semantics (L2 vs COSINE)
# Blindspot BS-02; contracts milvus_bc_radius_range_filter + milvus_behavioral_search_001
# source: https://github.com/milvus-io/milvus/blob/v2.3.22/internal/distributed/proxy/httpserver/handler_v1.go doc_version v2.3.22
import os, sys, math, time, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set"); sys.exit(2)
H = {"Content-Type": "application/json", "Authorization": "Bearer root:Milvus"}
DIM = 4
COL = "testvdb_sem_radius_02"

def safe_request(method, endpoint, json=None, timeout=20):
    try:
        r = requests.request(method, f"{BASE_URL}{endpoint}", json=json, headers=H, timeout=timeout)
        try: body = r.json()
        except Exception: body = r.text
        return r.status_code, body, r.text
    except Exception as e:
        return -1, str(e), str(e)

# cleanup then create L2 collection via v1 quick-create
safe_request("POST", "/v2/vectordb/collections/drop", json={"collectionName": COL})
s, b, r = safe_request("POST", "/v1/vector/collections/create", json={"collectionName": COL, "dimension": DIM, "metricType": "L2"})
print("create:", s, r[:200])
if s != 200 or (isinstance(b, dict) and b.get("code") != 200):
    print("VERDICT: SCRIPT_ERROR - create failed"); sys.exit(2)

# insert: origin 0-vec, close 0.1, far 10.0
rows = [{"vector": [0.0]*DIM}, {"vector": [0.1]*DIM}, {"vector": [10.0]*DIM}]
s, b, r = safe_request("POST", "/v1/vector/insert", json={"collectionName": COL, "data": rows})
print("insert:", s, r[:200])
time.sleep(2)

Q = [0.0]*DIM
defects = []

# 1. range_filter without radius -> code 1802
s, b, r = safe_request("POST", "/v1/vector/search",
    json={"collectionName": COL, "vector": Q, "limit": 10, "params": {"range_filter": 5.0}})
print("range_filter_only:", s, r[:300])
code = b.get("code") if isinstance(b, dict) else None
if s == 200 and code == 200:
    defects.append("range_filter without radius silently accepted (Type1_IllegalSuccess)")
elif not (s == 200 and isinstance(code, int) and code != 200):
    defects.append(f"range_filter-only rejection broke envelope: HTTP {s} code {code}")
else:
    msg = str(b.get("message", "")).lower()
    if "radius" not in msg and "range" not in msg and "param" not in msg:
        defects.append(f"error msg does not mention radius/range: {msg!r} (Type2_PoorDiagnostics)")

# 2. L2 radius semantics: radius=1.0 should include origin(0) + close(~0.04) exclude far(400)
s, b, r = safe_request("POST", "/v1/vector/search",
    json={"collectionName": COL, "vector": Q, "limit": 10, "params": {"radius": 1.0}})
print("l2_radius:", s, r[:400])
code = b.get("code") if isinstance(b, dict) else None
if s == 200 and code == 200:
    hits = b.get("data") or []
    if len(hits) != 2:
        defects.append(f"L2 radius=1.0 expected 2 hits (origin+close), got {len(hits)}: {r[:300]} (Type4_StateLogicViolation)")
    for h in hits:
        d = h.get("distance")
        if d is None or d < 0 or d > 1.0:
            defects.append(f"L2 distance {d} violates radius<=1.0 monotonic range (Type4)")

# 3. distance ordering ascending (L2 nearest-first)
s, b, r = safe_request("POST", "/v1/vector/search",
    json={"collectionName": COL, "vector": Q, "limit": 3})
print("l2_plain:", s, r[:400])
if s == 200 and isinstance(b, dict) and b.get("code") == 200:
    dists = [h.get("distance") for h in (b.get("data") or [])]
    if len(dists) == 3 and any(dists[i+1] < dists[i] - 1e-6 for i in range(len(dists)-1)):
        defects.append(f"L2 distances not ascending: {dists} (Type4_StateLogicViolation)")

try:
    safe_request("POST", "/v2/vectordb/collections/drop", json={"collectionName": COL})
except Exception:
    pass

if defects:
    print("VERDICT: DEFECT_FOUND")
    for d in defects: print("-", d)
    sys.exit(1)
print("VERDICT: NO_DEFECT")
