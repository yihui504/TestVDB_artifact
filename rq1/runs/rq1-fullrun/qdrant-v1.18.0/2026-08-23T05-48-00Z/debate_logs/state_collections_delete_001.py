# script_id: state_collections_delete_001
# strategy: delete_consistency
# endpoint: collections+delete
# Attack: qdrant_state_collections_delete_001 (explicit: DELETE existing => 200; DELETE missing => 404)
#   策略2 DELETE 后一致性 × collections+delete 语义核心
#   覆盖: delete existing => 200 | delete missing => 404 | deleted collection 上全部读端点状态语义
#   (get => 404, exists => exists:false, count/scroll/point+get/query => 404 而非 200 僵尸或 500)
# constraint_ids: qdrant_state_collections_delete_001, qdrant_inv_collection_gone_after_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned)
"""
State: create collection with 3 points, DELETE it (expect 200), then probe every
read endpoint on the deleted name. Per explicit contract:
  DELETE existing => 200; DELETE missing => 404; after delete GET => 404.
Defect signals:
  - zombie read: any data endpoint returns 200 on the deleted collection (Type4)
  - 5xx on any probe of a deleted collection (Type3)
  - DELETE of a missing collection returns 200 (Type1 illegal success)
"""
import requests, json, sys, os, time

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)
AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")

def safe_request(method, path, **kwargs):
    url = f"{BASE_URL}{path}"
    headers = kwargs.pop("headers", {"Content-Type": "application/json"})
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER
    try:
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        status = resp.status_code
        text = resp.text
        try:
            body = resp.json() if text else {}
        except (json.JSONDecodeError, ValueError):
            print(f"JSON_DECODE_ERROR: {text[:200]}")
            return status, None, text
        return status, body, text
    except requests.exceptions.RequestException as e:
        print(f"REQUEST_ERROR: {e}")
        return 0, None, ""

TS = str(int(time.time()))
COLL = f"st_cdel_basic_{TS}"
NEVER = f"st_cdel_never_{TS}"
DIM = 4

def cleanup():
    try:
        safe_request("DELETE", f"/collections/{COLL}")
    except Exception:
        pass

def defect(msg):
    print(msg)
    print("VERDICT: DEFECT_FOUND")
    sys.exit(1)

try:
    # setup: create + seed 3 points (wait=true 避开 wait=false 可见性 by-design)
    st, _, raw = safe_request("PUT", f"/collections/{COLL}",
                              json={"vectors": {"size": DIM, "distance": "Cosine"}})
    print(f"create: {st} {raw[:150]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)
    pts = [{"id": i, "vector": [0.1 * (i + 1)] * DIM, "payload": {"k": i}} for i in range(3)]
    st, _, raw = safe_request("PUT", f"/collections/{COLL}/points?wait=true", json={"points": pts})
    print(f"upsert: {st} {raw[:150]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)

    # core assertion 1: DELETE existing => 200
    st, _, raw = safe_request("DELETE", f"/collections/{COLL}")
    print(f"delete existing: {st} {raw[:200]}")
    if st == 500 or st == 0:
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — DELETE existing got {st}: {raw[:150]}")
    if st not in (200, 201):
        print(f"OBSERVATION: DELETE existing returned {st} (contract expects 200); continuing state checks")

    # core assertion 2: GET after delete => 404 (zombie check)
    st, _, raw = safe_request("GET", f"/collections/{COLL}")
    print(f"get deleted: {st} {raw[:200]}")
    if st == 200:
        defect("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — GET on deleted collection returned 200 (zombie)")
    if st >= 500 or st == 0:
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — GET deleted got {st}: {raw[:150]}")
    if st != 404:
        print(f"OBSERVATION: GET deleted returned {st}, expected 404")

    # exists: 200 with exists=false (contract: existence in body, never 404)
    st, body, raw = safe_request("GET", f"/collections/{COLL}/exists")
    print(f"exists deleted: {st} {raw[:200]}")
    exists_val = None
    if isinstance(body, dict) and isinstance(body.get("result"), dict):
        exists_val = body["result"].get("exists")
    if st == 200 and exists_val is True:
        defect("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — exists=true on deleted collection")
    if st >= 500 or st == 0:
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — exists deleted got {st}: {raw[:150]}")

    # data endpoints on deleted collection: all must be 404 (not 200 zombie, not 5xx)
    probes = [
        ("count", "POST", f"/collections/{COLL}/points/count", {"exact": True}),
        ("scroll", "POST", f"/collections/{COLL}/points/scroll", {"limit": 10}),
        ("point_get", "GET", f"/collections/{COLL}/points/0", None),
        ("query", "POST", f"/collections/{COLL}/points/query", {"query": [0.1] * DIM, "limit": 3}),
    ]
    for name, m, p, payload in probes:
        st, _, raw = safe_request(m, p, json=payload) if payload else safe_request(m, p)
        print(f"probe {name}: {st} {raw[:200]}")
        if st == 200:
            defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {name} returned 200 on deleted collection (zombie)")
        if st >= 500 or st == 0:
            defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {name} on deleted collection got {st}: {raw[:150]}")

    # core assertion 3: DELETE missing (just-deleted) => 404
    st, _, raw = safe_request("DELETE", f"/collections/{COLL}")
    print(f"delete missing (just deleted): {st} {raw[:200]}")
    if st == 200:
        defect("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — DELETE of missing collection returned 200 (contract: 404)")
    if st >= 500 or st == 0:
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — DELETE missing got {st}: {raw[:150]}")

    # DELETE never-created name => 404
    st, _, raw = safe_request("DELETE", f"/collections/{NEVER}")
    print(f"delete never-created: {st} {raw[:200]}")
    if st == 200:
        defect("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — DELETE of never-created collection returned 200 (contract: 404)")
    if st >= 500 or st == 0:
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — DELETE never-created got {st}: {raw[:150]}")

    print("VERDICT: NO_DEFECT")
    sys.exit(0)
except SystemExit:
    raise
except Exception as e:
    print(f"UNEXPECTED_ERROR: {e}")
    print("VERDICT: SCRIPT_ERROR")
    sys.exit(2)
finally:
    cleanup()
