# script_id: state_range_cc002_efconstruct_lifecycle_01
# strategy: index_state / state_consistency (策略6 索引配置状态一致性)
# endpoint: collections+create
# Attack: qdrant_range_collections_create_002 (hnsw_config.ef_construct >= 4) ×
#   (a) min-boundary(4) create 后索引功能一致性 (b) collections+update diff 路径下界拒绝
#   (c) update 后 GET echo 持久化
#   纯 create 侧 accept/reject 已由 boundary_collections_create_05 覆盖(NO_DEFECT)，本脚本只攻状态面
# constraint_ids: qdrant_range_collections_create_002
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
"""
State: create with ef_construct=4 (spec minimum, valid) -> verify HNSW index built
with the minimum config is FUNCTIONALLY consistent (upsert visible to query),
then PATCH collections+update:
  - ef_construct=3 (below diff minimum) => must be 4xx, NOT 200 (illegal success), NOT 500
  - ef_construct=64 (valid)            => 200 AND GET must echo 64 (persisted state)
Silent clamp/echo-divergence after accepted update = Type4_StateLogicViolation.
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
            body = resp.json() if text else {}
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
COLL = f"st_efc_{TS}"
CREATE = f"/collections/{COLL}"
COUNT = f"/collections/{COLL}/points/count"
QUERY = f"/collections/{COLL}/points/query"
VEC = [1.0, 0.0, 0.0, 0.0]

try:
    # 1. create at spec minimum ef_construct=4
    st, body, raw = safe_request("PUT", CREATE, json={
        "vectors": {"size": 4, "distance": "Cosine"},
        "hnsw_config": {"ef_construct": 4},
    })
    print(f"create ef_construct=4: {st} {raw[:300]}")
    if st == 500:
        print("DEFECT detail: 500 on valid minimum create")
        report("DEFECT_FOUND", 1)
    if st not in (200, 201):
        print("setup create failed (not defect, cannot proceed)")
        report("SCRIPT_ERROR", 2)

    # 2. functional consistency: min-config index must serve queries
    pts = [{"id": 1, "vector": [1.0, 0.0, 0.0, 0.0]},
           {"id": 2, "vector": [0.0, 1.0, 0.0, 0.0]},
           {"id": 3, "vector": [0.0, 0.0, 1.0, 0.0]}]
    st, body, raw = safe_request("PUT", f"{CREATE}/points?wait=true", json={"points": pts})
    print(f"upsert: {st} {raw[:200]}")
    if st != 200:
        print("upsert failed during setup")
        report("SCRIPT_ERROR", 2)

    st, body, raw = safe_request("POST", COUNT, json={"exact": True})
    print(f"count: {st} {raw[:200]}")
    cnt = (body or {}).get("result", {}).get("count") if isinstance(body, dict) else None
    if cnt != 3:
        print(f"DEFECT detail: count={cnt} expected 3 after 3 upserts (wait=true)")
        report("DEFECT_FOUND", 1)

    st, body, raw = safe_request("POST", QUERY, json={
        "query": {"nearest": VEC}, "limit": 3})
    print(f"query: {st} {raw[:400]}")
    if st == 500:
        print("DEFECT detail: 500 on query against ef_construct=4 collection")
        report("DEFECT_FOUND", 1)
    hits = []
    if isinstance(body, dict):
        hits = body.get("result") or []
    if not hits or hits[0].get("id") != 1:
        print(f"DEFECT detail: identical vector not top hit with min ef_construct; hits={hits[:2]}")
        report("DEFECT_FOUND", 1)

    # 3. PATCH below diff minimum => must be rejected
    st, body, raw = safe_request("PATCH", CREATE, json={"hnsw_config": {"ef_construct": 3}})
    print(f"patch ef_construct=3: {st} {raw[:300]}")
    if st == 200:
        print("DEFECT detail (Type1): ef_construct=3 accepted on update (contract: >=4)")
        report("DEFECT_FOUND", 1)
    if st >= 500:
        print("DEFECT detail (Type3): 5xx on invalid update")
        report("DEFECT_FOUND", 1)

    # 4. PATCH valid => accepted AND persisted in GET echo
    st, body, raw = safe_request("PATCH", CREATE, json={"hnsw_config": {"ef_construct": 64}})
    print(f"patch ef_construct=64: {st} {raw[:200]}")
    if st != 200:
        print(f"valid update rejected: {st}")
        report("SCRIPT_ERROR", 2)

    st, body, raw = safe_request("GET", CREATE)
    print(f"get after patch: {st} {raw[:500]}")
    cfg = None
    if isinstance(body, dict):
        cfg = (((body.get("result") or {}).get("config") or {}).get("hnsw_config") or {})
    echoed = cfg.get("ef_construct")
    if echoed != 64:
        print(f"DEFECT detail (Type4): accepted update ef_construct=64 but GET echoes {echoed}")
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
