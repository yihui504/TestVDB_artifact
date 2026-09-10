# script_id: state_range_cc003_fullscan_diff_02
# strategy: state_consistency (策略1 CRUD 后配置状态一致性 × create/diff 双路径)
# endpoint: collections+create
# Attack: qdrant_range_collections_create_003 (hnsw_config.full_scan_threshold
#   >= 0 create / >= 10 diff) × collections+update diff 路径下界 + GET echo 持久化。
#   create 侧 accept/reject 已由 boundary_collections_create_05 覆盖，本脚本攻
#   (a) update diff 路径 5 (<10) 是否非法成功 (b) update 接受值是否持久化 echo
# constraint_ids: qdrant_range_collections_create_003
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
"""
State: create with full_scan_threshold=100 -> GET must echo 100 (persisted).
PATCH collections+update:
  - full_scan_threshold=5  (below diff minimum 10) => 4xx expected; 200 = Type1
  - full_scan_threshold=10 (diff minimum)         => 200 expected AND GET echo == 10
Accepted-but-not-persisted or silently-changed value = Type4_StateLogicViolation.
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


def get_echoed_fullscan():
    st, body, raw = safe_request("GET", CREATE)
    print(f"get: {st} {raw[:500]}")
    if st != 200 or not isinstance(body, dict):
        return None
    cfg = (((body.get("result") or {}).get("config") or {}).get("hnsw_config") or {})
    return cfg.get("full_scan_threshold")


TS = str(int(time.time())) + str(os.getpid() % 1000)
COLL = f"st_fst_{TS}"
CREATE = f"/collections/{COLL}"

try:
    st, body, raw = safe_request("PUT", CREATE, json={
        "vectors": {"size": 4, "distance": "Cosine"},
        "hnsw_config": {"full_scan_threshold": 100},
    })
    print(f"create full_scan_threshold=100: {st} {raw[:300]}")
    if st == 500:
        print("DEFECT detail (Type3): 500 on valid create")
        report("DEFECT_FOUND", 1)
    if st not in (200, 201):
        print("setup create failed (not defect)")
        report("SCRIPT_ERROR", 2)

    echoed = get_echoed_fullscan()
    if echoed != 100:
        print(f"DEFECT detail (Type4): created with full_scan_threshold=100 but GET echoes {echoed}")
        report("DEFECT_FOUND", 1)

    # diff path: below minimum 10 -> must be rejected
    st, body, raw = safe_request("PATCH", CREATE, json={
        "hnsw_config": {"full_scan_threshold": 5}})
    print(f"patch full_scan_threshold=5: {st} {raw[:300]}")
    if st == 200:
        print("DEFECT detail (Type1): full_scan_threshold=5 accepted on update (diff minimum 10)")
        report("DEFECT_FOUND", 1)
    if st >= 500:
        print("DEFECT detail (Type3): 5xx on invalid update")
        report("DEFECT_FOUND", 1)

    # after rejected patch, state must be unchanged (100)
    echoed = get_echoed_fullscan()
    if echoed != 100:
        print(f"DEFECT detail (Type4): rejected patch mutated state; echo now {echoed}")
        report("DEFECT_FOUND", 1)

    # diff minimum 10 -> accepted AND persisted
    st, body, raw = safe_request("PATCH", CREATE, json={
        "hnsw_config": {"full_scan_threshold": 10}})
    print(f"patch full_scan_threshold=10: {st} {raw[:200]}")
    if st != 200:
        print(f"valid update at diff minimum rejected: {st}")
        report("SCRIPT_ERROR", 2)
    echoed = get_echoed_fullscan()
    if echoed != 10:
        print(f"DEFECT detail (Type4): accepted update full_scan_threshold=10 but GET echoes {echoed}")
        report("DEFECT_FOUND", 1)

    # functional sanity: data ops still consistent after config transitions
    pts = [{"id": 1, "vector": [1.0, 0.0, 0.0, 0.0]},
           {"id": 2, "vector": [0.0, 1.0, 0.0, 0.0]}]
    st, body, raw = safe_request("PUT", f"{CREATE}/points?wait=true", json={"points": pts})
    print(f"upsert: {st} {raw[:150]}")
    st, body, raw = safe_request("POST", f"{CREATE}/points/count", json={"exact": True})
    print(f"count: {st} {raw[:150]}")
    cnt = (body or {}).get("result", {}).get("count") if isinstance(body, dict) else None
    if cnt != 2:
        print(f"DEFECT detail (Type4): count={cnt} expected 2 after config transitions")
        report("DEFECT_FOUND", 1)

    print("all state checks passed")
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
