# script_id: state_bhvr_cc002_create_visibility_06
# strategy: state_consistency (策略1 创建后立即可见性)
# endpoint: collections+create
# Attack: assertions::qdrant_behavioral_collections_create_002 (200
#   CollectionOperationResponse {result, status ok, time}) ×
#   qdrant_inv_collection_visible_after_create_001（create 200 后 GET 200 + status
#   ∈ {green,yellow,red} + config echo）——响应形状断言 + 零 sleep 立即可见性
# constraint_ids: qdrant_type_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
"""
State: PUT create (valid) => 200. Assert response shape per behavioral_002:
body contains result and status=="ok". Then IMMEDIATELY (no sleep):
  - GET /collections/{c} => 200, result.status is a valid enum value, config
    echoes vectors.size=4 (requested config persisted)
  - GET /collections/{c}/exists => result.exists == true
  - GET /collections => list contains name
Any immediate-invisibility or shape divergence = Type4_StateLogicViolation.
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


TS = str(int(time.time())) + str(os.getpid() % 1000)
COLL = f"st_vis_{TS}"
CREATE = f"/collections/{COLL}"

try:
    st, body, raw = safe_request("PUT", CREATE, json={
        "vectors": {"size": 4, "distance": "Cosine"},
        "shard_number": 1})
    print(f"create: {st} {raw[:300]}")
    if st != 200:
        print(f"setup create returned {st} (not attackable here)")
        report("SCRIPT_ERROR", 2)

    # behavioral_002: response shape
    if not isinstance(body, dict) or "result" not in body:
        print(f"DEFECT detail (Type4): 200 response missing 'result' field: {raw[:200]}")
        report("DEFECT_FOUND", 1)
    status_field = body.get("status")
    if status_field != "ok":
        print(f"DEFECT detail (Type4): 200 response status={status_field!r}, expected 'ok'")
        report("DEFECT_FOUND", 1)

    # immediate visibility: GET
    st, body, raw = safe_request("GET", CREATE)
    print(f"immediate get: {st} {raw[:500]}")
    if st != 200:
        print(f"DEFECT detail (Type4): create returned 200 but immediate GET={st}")
        report("DEFECT_FOUND", 1)
    if isinstance(body, dict):
        res = body.get("result") or {}
        cstatus = res.get("status")
        print(f"collection status: {cstatus}")
        if cstatus not in ("green", "yellow", "red"):
            print(f"DEFECT detail (Type4): collection status {cstatus!r} not in enum")
            report("DEFECT_FOUND", 1)
        vc = ((res.get("config") or {}).get("params") or {}).get("vectors")
        if not (isinstance(vc, dict) and vc.get("size") == 4):
            print(f"DEFECT detail (Type4): config echo missing requested size=4: {vc}")
            report("DEFECT_FOUND", 1)
    else:
        print("DEFECT detail (Type4): GET body not JSON")
        report("DEFECT_FOUND", 1)

    # immediate visibility: exists
    st, body, raw = safe_request("GET", f"{CREATE}/exists")
    print(f"immediate exists: {st} {raw[:150]}")
    ex = None
    if isinstance(body, dict):
        ex = (body.get("result") or {}).get("exists")
    if ex is not True:
        print(f"DEFECT detail (Type4): exists={ex} immediately after create 200")
        report("DEFECT_FOUND", 1)

    # immediate visibility: list
    st, body, raw = safe_request("GET", "/collections")
    listed = False
    if isinstance(body, dict):
        listed = COLL in ((body.get("result") or {}).get("collections") or [])
    print(f"in list immediately: {listed}")
    if not listed:
        print("DEFECT detail (Type4): collection absent from list immediately after create 200")
        report("DEFECT_FOUND", 1)

    # immediate writability: upsert + exact count
    st, body, raw = safe_request("PUT", f"{CREATE}/points?wait=true", json={
        "points": [{"id": 1, "vector": [1.0, 0.0, 0.0, 0.0]}]})
    print(f"immediate upsert: {st} {raw[:150]}")
    if st == 500:
        print("DEFECT detail (Type3): 500 on upsert immediately after create 200")
        report("DEFECT_FOUND", 1)
    if st == 200:
        st, body, raw = safe_request("POST", f"{CREATE}/points/count", json={"exact": True})
        print(f"count: {st} {raw[:150]}")
        cnt = (body or {}).get("result", {}).get("count") if isinstance(body, dict) else None
        if cnt != 1:
            print(f"DEFECT detail (Type4): count={cnt} expected 1")
            report("DEFECT_FOUND", 1)

    print("create visibility + shape checks passed")
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
