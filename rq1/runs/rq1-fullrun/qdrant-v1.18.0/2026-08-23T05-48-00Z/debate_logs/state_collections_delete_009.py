# script_id: state_collections_delete_009
# strategy: delete_consistency
# endpoint: collections+delete
# Attack: qdrant_state_collections_delete_001 × 策略2 DELETE 后一致性（读端点广度扫描）
#   覆盖: delete 后 collections+list 不得再含该名字（残留 = Type4）；
#   collections+exists => exists:false；optimizations / cluster info 对已删集合 =>
#   404（500 = Type3；200 空 result 只记 OBSERVATION，契约未规定）；
#   兄弟集合 B 全程不受影响（count 不变）
# constraint_ids: qdrant_state_collections_delete_001, qdrant_inv_collection_gone_after_delete_001,
#   qdrant_bc_collection_delete_isolation_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned)
"""
Post-delete metadata breadth: after DELETE, the collection name must vanish from
collections+list, exists must report false, and admin read endpoints
(optimizations, cluster info) must respond 404 — never 5xx. Sibling collection
stays untouched.
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
COLL_A = f"st_cdel_meta_a_{TS}"
COLL_B = f"st_cdel_meta_b_{TS}"
DIM = 4

def cleanup():
    for name in (COLL_A, COLL_B):
        try:
            safe_request("DELETE", f"/collections/{name}")
        except Exception:
            pass

def defect(msg):
    print(msg)
    print("VERDICT: DEFECT_FOUND")
    sys.exit(1)

def count_exact(name):
    st, body, raw = safe_request("POST", f"/collections/{name}/points/count", json={"exact": True})
    print(f"count[{name}]: {st} {raw[:200]}")
    if st != 200 or not isinstance(body, dict):
        return None
    r = body.get("result")
    return r.get("count") if isinstance(r, dict) else None

try:
    # setup A (victim) + B (sibling control)
    for name, n in ((COLL_A, 4), (COLL_B, 5)):
        st, _, raw = safe_request("PUT", f"/collections/{name}",
                                  json={"vectors": {"size": DIM, "distance": "Cosine"}})
        print(f"create {name}: {st} {raw[:150]}")
        if st not in (200, 201):
            print("VERDICT: SCRIPT_ERROR")
            sys.exit(2)
        pts = [{"id": i, "vector": [0.1 * (i + 1)] * DIM} for i in range(n)]
        st, _, raw = safe_request("PUT", f"/collections/{name}/points?wait=true", json={"points": pts})
        print(f"upsert {name}: {st} {raw[:150]}")

    # sanity: list contains both
    st, body, raw = safe_request("GET", "/collections")
    print(f"list pre-delete: {st} {raw[:300]}")
    names_pre = set()
    if st == 200 and isinstance(body, dict):
        for c in (body.get("result") or {}).get("collections", []):
            if isinstance(c, dict):
                names_pre.add(c.get("name"))
    if COLL_A not in names_pre or COLL_B not in names_pre:
        print(f"OBSERVATION: pre-delete list missing test collections: {names_pre}")

    # delete A
    st, _, raw = safe_request("DELETE", f"/collections/{COLL_A}")
    print(f"delete A: {st} {raw[:200]}")
    if st not in (200, 201):
        print(f"OBSERVATION: DELETE returned {st}; continuing")

    # check 1: list no longer contains A, still contains B
    st, body, raw = safe_request("GET", "/collections")
    print(f"list post-delete: {st} {raw[:300]}")
    names_post = set()
    if st == 200 and isinstance(body, dict):
        for c in (body.get("result") or {}).get("collections", []):
            if isinstance(c, dict):
                names_post.add(c.get("name"))
    if st >= 500 or st == 0:
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — collections list got {st}: {raw[:150]}")
    if COLL_A in names_post:
        defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — deleted collection still listed in collections+list: {sorted(names_post)}")
    if COLL_B not in names_post:
        defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — sibling B vanished from list after deleting A: {sorted(names_post)}")

    # check 2: exists A => false
    st, body, raw = safe_request("GET", f"/collections/{COLL_A}/exists")
    print(f"exists A: {st} {raw[:200]}")
    exists_val = None
    if isinstance(body, dict) and isinstance(body.get("result"), dict):
        exists_val = body["result"].get("exists")
    if st == 200 and exists_val is True:
        defect("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — exists=true for deleted collection")
    if st >= 500 or st == 0:
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — exists A got {st}: {raw[:150]}")

    # check 3: optimizations on deleted A
    st, _, raw = safe_request("GET", f"/collections/{COLL_A}/optimizations")
    print(f"optimizations A: {st} {raw[:200]}")
    if st == 200:
        print("OBSERVATION: optimizations returned 200 for deleted collection (empty result tolerated; contract silent)")
    if st >= 500 or st == 0:
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — optimizations on deleted got {st}: {raw[:150]}")

    # check 4: cluster info on deleted A
    st, _, raw = safe_request("GET", f"/collections/{COLL_A}/cluster")
    print(f"cluster A: {st} {raw[:200]}")
    if st == 200:
        print("OBSERVATION: cluster info returned 200 for deleted collection (contract silent; tolerated)")
    if st >= 500 or st == 0:
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — cluster info on deleted got {st}: {raw[:150]}")

    # check 5: sibling B untouched
    c = count_exact(COLL_B)
    if c != 5:
        defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — sibling B count changed after deleting A: expected 5, got {c}")

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
