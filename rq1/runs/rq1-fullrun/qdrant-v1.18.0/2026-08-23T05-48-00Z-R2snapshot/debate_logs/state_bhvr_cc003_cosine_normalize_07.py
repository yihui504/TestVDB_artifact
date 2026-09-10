# script_id: state_bhvr_cc003_cosine_normalize_07
# strategy: state_consistency (策略3 upsert 后存储状态一致性)
# endpoint: collections+create
# Attack: assertions::qdrant_behavioral_collections_create_003 (Cosine = dot over
#   normalized vectors; "vectors automatically normalized during upload" by-design) ×
#   存储状态验证：非单位向量 upsert 后 GET(with_vector=true) 必须返回归一化向量
# constraint_ids: qdrant_type_collections_create_001
# source_url: https://qdrant.tech/documentation/concepts/collections/
# doc_version: 1.18.x (versioned)
"""
State: create Cosine dim=2; upsert id=1 [3.0,4.0] (norm 5) and id=2 [0.0,5.0].
Per documented by-design behavior, stored vectors are normalized at upload.
  - GET points with_vector=true: id=1 must be [0.6, 0.8] (norm 1.0 ±1e-3)
  - search with original [3,4]: top hit id=1, cosine score ~1.0 (>= 0.999)
Stored vector not normalized (norm != 1) while distance=Cosine = documented
normalization not applied => Type4_StateLogicViolation candidate (judge decides
against current-only concept docs; versioned spec wins on conflict).
"""
import requests, json, sys, os, time, math

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
COLL = f"st_cos_{TS}"
CREATE = f"/collections/{COLL}"

try:
    st, body, raw = safe_request("PUT", CREATE, json={
        "vectors": {"size": 2, "distance": "Cosine"}})
    print(f"create Cosine dim2: {st} {raw[:200]}")
    if st != 200:
        report("SCRIPT_ERROR", 2)

    st, body, raw = safe_request("PUT", f"{CREATE}/points?wait=true", json={"points": [
        {"id": 1, "vector": [3.0, 4.0]},
        {"id": 2, "vector": [0.0, 5.0]},
    ]})
    print(f"upsert non-unit vectors: {st} {raw[:150]}")
    if st != 200:
        report("SCRIPT_ERROR", 2)

    # stored-state check: normalization persisted?
    st, body, raw = safe_request("POST", f"{CREATE}/points/get", json={
        "ids": [1, 2], "with_vector": True, "with_payload": False})
    print(f"get with_vector: {st} {raw[:400]}")
    if st != 200:
        report("SCRIPT_ERROR", 2)
    results = []
    if isinstance(body, dict):
        results = body.get("result") or []
    vec_by_id = {}
    for p in results:
        if isinstance(p, dict) and "vector" in p:
            vec_by_id[p.get("id")] = p.get("vector")
    print(f"stored vectors: {vec_by_id}")

    v1 = vec_by_id.get(1)
    if v1 is None:
        print("DEFECT detail (Type4): point 1 has no vector returned with with_vector=true")
        report("DEFECT_FOUND", 1)
    norm = math.sqrt(sum(x * x for x in v1))
    print(f"norm of stored id=1 vector: {norm}")
    if abs(norm - 1.0) > 1e-3:
        print(f"DEFECT detail (Type4): Cosine collection stored NON-normalized vector {v1} "
              f"(norm={norm:.4f}); docs: vectors automatically normalized during upload")
        report("DEFECT_FOUND", 1)
    if abs(v1[0] - 0.6) > 1e-3 or abs(v1[1] - 0.8) > 1e-3:
        print(f"DEFECT detail (Type4): expected normalized [0.6, 0.8], got {v1}")
        report("DEFECT_FOUND", 1)

    # distance semantics: search with ORIGINAL non-unit query must behave as cosine
    st, body, raw = safe_request("POST", f"{CREATE}/points/search", json={
        "vector": [3.0, 4.0], "limit": 2, "with_payload": False})
    print(f"search [3,4]: {st} {raw[:400]}")
    if st != 200:
        report("SCRIPT_ERROR", 2)
    hits = []
    if isinstance(body, dict):
        hits = body.get("result") or []
    if not hits or hits[0].get("id") != 1:
        print(f"DEFECT detail (Type4): search top hit {hits[:1]} != id 1 for identical-direction query")
        report("DEFECT_FOUND", 1)
    score = hits[0].get("score")
    print(f"top score: {score}")
    if score is None or score < 0.999:
        print(f"DEFECT detail (Type4): cosine score for identical direction = {score}, expected ~1.0")
        report("DEFECT_FOUND", 1)

    # count consistency alongside
    st, body, raw = safe_request("POST", f"{CREATE}/points/count", json={"exact": True})
    print(f"count: {st} {raw[:150]}")
    cnt = (body or {}).get("result", {}).get("count") if isinstance(body, dict) else None
    if cnt != 2:
        print(f"DEFECT detail (Type4): count={cnt} expected 2")
        report("DEFECT_FOUND", 1)

    print("cosine normalization state checks passed")
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
