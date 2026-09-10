# script_id: state_cc001_dup_config_preserve_04
# strategy: state_transition (模式 B 重复创建 × 不同配置变体 — 未覆盖面)
# endpoint: collections+create
# Attack: qdrant_state_collections_create_001 (PUT existing name => 4xx conflict) ×
#   不同配置(dim/distance 不同)的重复创建：拒绝后原配置与数据必须原样保留
#   （无 partial mutation）；delete 后同名重建 dim=8 必须 200（名字可复用）。
#   前轮 state_collections_create_001 已测同配置重复(SEQUENTIAL)，本脚本攻
#   不同配置重复 + 配置不被篡改 + delete→recreate 迁移
# constraint_ids: qdrant_state_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
"""
State: create(dim=4, Cosine) -> upsert 2 points -> PUT same name with dim=8/Euclid.
Expected: 4xx conflict. NOT 200 (would silently destroy/redefine collection = Type1),
NOT 5xx (Type3). After rejection: GET config still size=4/Cosine (Type4 if mutated),
count still 2. Then DELETE -> 200, GET -> 404; recreate same name with dim=8 -> 200
and GET echoes size=8 (name reusable after proper delete).
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
COLL = f"st_dupc_{TS}"
CREATE = f"/collections/{COLL}"

try:
    st, body, raw = safe_request("PUT", CREATE, json={
        "vectors": {"size": 4, "distance": "Cosine"}})
    print(f"create dim4: {st} {raw[:200]}")
    if st not in (200, 201):
        report("SCRIPT_ERROR", 2)

    pts = [{"id": 1, "vector": [1.0, 0.0, 0.0, 0.0]},
           {"id": 2, "vector": [0.0, 1.0, 0.0, 0.0]}]
    st, body, raw = safe_request("PUT", f"{CREATE}/points?wait=true", json={"points": pts})
    print(f"upsert: {st} {raw[:150]}")
    if st != 200:
        report("SCRIPT_ERROR", 2)

    # duplicate create with DIFFERENT config
    st, body, raw = safe_request("PUT", CREATE, json={
        "vectors": {"size": 8, "distance": "Euclid"}})
    print(f"duplicate create dim8/Euclid: {st} {raw[:300]}")
    if st == 200:
        print("DEFECT detail (Type1): duplicate create with different config ACCEPTED — "
              "redefines existing collection (data-destructive overwrite)")
        report("DEFECT_FOUND", 1)
    if st >= 500:
        print("DEFECT detail (Type3): 5xx on duplicate create")
        report("DEFECT_FOUND", 1)
    if st < 400:
        print(f"DEFECT detail: unexpected status {st} for duplicate create")
        report("DEFECT_FOUND", 1)

    # original config + data must be untouched
    st, body, raw = safe_request("GET", CREATE)
    print(f"get after rejected dup: {st} {raw[:500]}")
    vc = None
    if isinstance(body, dict):
        vc = (((body.get("result") or {}).get("config") or {}).get("params") or {}).get("vectors")
    print(f"vectors config now: {vc}")
    if not (isinstance(vc, dict) and vc.get("size") == 4 and vc.get("distance") == "Cosine"):
        print("DEFECT detail (Type4): rejected duplicate create mutated original vectors config")
        report("DEFECT_FOUND", 1)

    st, body, raw = safe_request("POST", f"{CREATE}/points/count", json={"exact": True})
    print(f"count after rejected dup: {st} {raw[:150]}")
    cnt = (body or {}).get("result", {}).get("count") if isinstance(body, dict) else None
    if cnt != 2:
        print(f"DEFECT detail (Type4): count={cnt} expected 2 after rejected duplicate create")
        report("DEFECT_FOUND", 1)

    # proper delete then recreate with the previously-conflicting config
    st, body, raw = safe_request("DELETE", CREATE)
    print(f"delete: {st} {raw[:150]}")
    if st != 200:
        report("SCRIPT_ERROR", 2)
    st, body, raw = safe_request("GET", CREATE)
    print(f"get after delete: {st} {raw[:150]}")
    if st != 404:
        print(f"DEFECT detail (Type4): deleted collection GET returns {st}, expected 404")
        report("DEFECT_FOUND", 1)

    st, body, raw = safe_request("PUT", CREATE, json={
        "vectors": {"size": 8, "distance": "Euclid"}})
    print(f"recreate dim8 after delete: {st} {raw[:200]}")
    if st != 200:
        print(f"DEFECT detail (Type4): name not reusable after proper delete: {st} {raw[:200]}")
        report("DEFECT_FOUND", 1)
    st, body, raw = safe_request("GET", CREATE)
    vc = None
    if isinstance(body, dict):
        vc = (((body.get("result") or {}).get("config") or {}).get("params") or {}).get("vectors")
    print(f"recreated vectors config: {vc}")
    if not (isinstance(vc, dict) and vc.get("size") == 8 and vc.get("distance") == "Euclid"):
        print("DEFECT detail (Type4): recreated collection does not echo new config")
        report("DEFECT_FOUND", 1)

    print("all lifecycle checks passed")
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
