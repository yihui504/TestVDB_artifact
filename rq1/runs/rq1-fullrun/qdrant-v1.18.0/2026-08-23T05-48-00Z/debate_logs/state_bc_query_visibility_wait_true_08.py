# script_id: state_bc_query_visibility_wait_true_08
# strategy: state_consistency (模式 A 创建→修改→删除→恢复 × query 可见性)
# endpoint: collections+create (+ points+upsert / points+query / points+delete)
# Attack: behavioral_contracts::qdrant_bc_create_query_visibility_001
#   (scenario: create; upsert wait=true; query nearest same vector =>
#    upserted point top hit, distance ~0 / cosine score ~1.0) × 全生命周期:
#    upsert 后可见 -> delete 后不可见 -> re-upsert 后再可见（含 count 全程一致）
# constraint_ids: qdrant_type_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points
# doc_version: 1.18.x (versioned)
"""
Lifecycle (wait=true strong-read-your-write):
  1. create dim=4 Cosine; upsert ids 101/102/103 (orthonormal vectors) wait=true
  2. IMMEDIATELY query nearest = v(101): top hit must be 101 with score >= 0.999;
     points+get returns all 3 ids; exact count == 3
  3. delete 101 wait=true; IMMEDIATELY query v(101): 101 must NOT appear;
     count == 2; top hit should be 102 or 103
  4. re-upsert 101 with v(102) direction; query v(102): 101 visible again; count == 3
Violation at any step = Type4_StateLogicViolation (wait=true broken visibility).
"""
import requests, json, sys, os, time

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("TESTVDB_DB_URL not set")
    print("VERDICT: SCRIPT_ERROR")
    sys.exit(2)
AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")


def safe_request(method, path, **kwargs):
    url = f"{BASE_URL}{path}"
    headers = kwargs.pop("headers", {"Content-Type": "application/json"})
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER
    try:
        resp = requests.request(method, url, headers=headers, timeout=60, **kwargs)
        status = resp.status_code
        text = resp.text
        try:
            body = resp.json() if text else None
        except (json.JSONDecodeError, ValueError):
            body = None
        return status, body, text
    except requests.exceptions.RequestException as e:
        print(f"REQUEST_ERROR: {e}")
        return 0, None, ""


def report(verdict, code):
    print(f"VERDICT: {verdict}")
    sys.exit(code)


def exact_count():
    st, body, raw = safe_request("POST", COUNT, json={"exact": True})
    print(f"count: {st} {raw[:150]}")
    if isinstance(body, dict):
        return (body.get("result") or {}).get("count")
    return None


def query_nearest(vec, limit=3):
    st, body, raw = safe_request("POST", QUERY, json={
        "query": {"nearest": vec}, "limit": limit, "with_payload": False})
    print(f"query: {st} {raw[:400]}")
    hits = []
    if isinstance(body, dict):
        hits = body.get("result") or []
    return st, hits


V101 = [1.0, 0.0, 0.0, 0.0]
V102 = [0.0, 1.0, 0.0, 0.0]
V103 = [0.0, 0.0, 1.0, 0.0]
TS = str(int(time.time())) + str(os.getpid() % 1000)
COLL = f"st_bcvt_{TS}"
CREATE = f"/collections/{COLL}"
COUNT = f"{CREATE}/points/count"
QUERY = f"{CREATE}/points/query"

try:
    st, body, raw = safe_request("PUT", CREATE, json={
        "vectors": {"size": 4, "distance": "Cosine"}})
    print(f"create: {st} {raw[:150]}")
    if st != 200:
        report("SCRIPT_ERROR", 2)

    # step 1: upsert wait=true
    st, body, raw = safe_request("PUT", f"{CREATE}/points?wait=true", json={"points": [
        {"id": 101, "vector": V101},
        {"id": 102, "vector": V102},
        {"id": 103, "vector": V103}]})
    print(f"upsert x3 wait=true: {st} {raw[:150]}")
    if st != 200:
        report("SCRIPT_ERROR", 2)

    # step 2: immediate visibility
    qst, hits = query_nearest(V101)
    if qst == 500:
        print("DEFECT detail (Type3): 500 on query after wait=true upsert")
        report("DEFECT_FOUND", 1)
    if not hits or hits[0].get("id") != 101 or (hits[0].get("score") or 0) < 0.999:
        print(f"DEFECT detail (Type4): wait=true upsert not immediately visible: {hits[:2]}")
        report("DEFECT_FOUND", 1)

    st, body, raw = safe_request("POST", f"{CREATE}/points/get", json={
        "ids": [101, 102, 103], "with_vector": False})
    print(f"get ids: {st} {raw[:300]}")
    got_ids = set()
    if isinstance(body, dict):
        got_ids = {p.get("id") for p in (body.get("result") or []) if isinstance(p, dict)}
    if got_ids != {101, 102, 103}:
        print(f"DEFECT detail (Type4): points+get returned {got_ids} after wait=true upsert")
        report("DEFECT_FOUND", 1)
    if exact_count() != 3:
        print("DEFECT detail (Type4): exact count != 3 after 3 wait=true upserts")
        report("DEFECT_FOUND", 1)

    # step 3: delete then immediate invisibility
    st, body, raw = safe_request("POST", f"{CREATE}/points/delete?wait=true",
                                 json={"points": [101]})
    print(f"delete 101 wait=true: {st} {raw[:150]}")
    if st != 200:
        report("SCRIPT_ERROR", 2)
    qst, hits = query_nearest(V101)
    ids = [h.get("id") for h in hits]
    if 101 in ids:
        print(f"DEFECT detail (Type4): deleted point 101 still queryable: {ids}")
        report("DEFECT_FOUND", 1)
    if exact_count() != 2:
        print("DEFECT detail (Type4): exact count != 2 after delete")
        report("DEFECT_FOUND", 1)

    # step 4: re-upsert resurrects visibility
    st, body, raw = safe_request("PUT", f"{CREATE}/points?wait=true", json={"points": [
        {"id": 101, "vector": V102}]})
    print(f"re-upsert 101 (v102 dir): {st} {raw[:150]}")
    if st != 200:
        report("SCRIPT_ERROR", 2)
    qst, hits = query_nearest(V102)
    ids = [h.get("id") for h in hits]
    if 101 not in ids:
        print(f"DEFECT detail (Type4): re-upserted 101 not visible: {ids}")
        report("DEFECT_FOUND", 1)
    if exact_count() != 3:
        print("DEFECT detail (Type4): exact count != 3 after re-upsert")
        report("DEFECT_FOUND", 1)

    print("wait=true visibility lifecycle checks passed")
    report("NO_DEFECT", 0)
except SystemExit:
    raise
except Exception as e:
    print(f"UNEXPECTED_ERROR: {type(e).__name__}: {e}")
    report("SCRIPT_ERROR", 2)
finally:
    try:
        safe_request("DELETE", CREATE)
    except Exception:
        pass
