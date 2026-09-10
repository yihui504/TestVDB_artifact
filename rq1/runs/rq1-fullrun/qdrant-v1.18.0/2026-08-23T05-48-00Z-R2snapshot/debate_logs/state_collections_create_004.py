# script_id: state_collections_create_004
# strategy: index_state / state_transition (sparse/dense 混合配置状态一致性)
# endpoint: collections+create
# Attack: qdrant_type_collections_create_009 + qdrant_type_collections_create_010
#   (sparse vectors 命名约束 × 同名 dense/sparse 冲突; 全 collection 同名维度一致性)
# constraint_ids: qdrant_type_collections_create_009, qdrant_type_collections_create_010
# source_url: https://qdrant.tech/documentation/concepts/collections/
# doc_version: 1.18.x (versioned)
# Blindspot: BS-03 (状态一致性 — create 后配置与实际索引行为一致)
"""
State: create collection with named dense vector "v" (dim 4).
Then attempt to upsert a point whose "v" has a DIFFERENT dimension (5) —
server must reject (400/422), and the rejected upsert must NOT alter count.
Also: attempt upsert with sparse vector using SAME name "v" (dense/sparse
name collision) — must be rejected per constraint 009, count unchanged.
Verifies create-config vs data-plane consistency (state invariant:
one dimensionality per vector name, enforced at write time, no partial commits).
"""
import requests, json, sys, os, time

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
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
COLL = f"st_cc_dim_{TS}"

def cleanup():
    try:
        safe_request("DELETE", f"/collections/{COLL}")
    except Exception:
        pass

def count_exact():
    st, body, raw = safe_request("POST", f"/collections/{COLL}/points/count", json={"exact": True})
    print(f"count: {st} {raw[:200]}")
    try:
        return body["result"]["count"]
    except (TypeError, KeyError):
        return None

try:
    st, _, raw = safe_request("PUT", f"/collections/{COLL}", json={
        "vectors": {"v": {"size": 4, "distance": "Cosine"}}})
    print(f"create: {st} {raw[:200]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)

    # baseline good point
    st, _, raw = safe_request("PUT", f"/collections/{COLL}/points?wait=true",
        json={"points": [{"id": 1, "vector": {"v": [0.1, 0.2, 0.3, 0.4]}}]})
    print(f"upsert good: {st} {raw[:200]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)
    c0 = count_exact()
    if c0 != 1:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — baseline count expected 1, got {c0}")
        sys.exit(1)

    # wrong dimension under same vector name — must be rejected
    st, _, raw = safe_request("PUT", f"/collections/{COLL}/points?wait=true",
        json={"points": [{"id": 2, "vector": {"v": [1.0, 2.0, 3.0, 4.0, 5.0]}}]})
    print(f"upsert dim5: {st} {raw[:300]}")
    if st in (200, 201):
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — wrong-dimension vector accepted, violates per-name dimensionality")
        sys.exit(1)
    if st >= 500:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — wrong-dimension upsert returned {st}")
        sys.exit(1)

    # sparse vector colliding with dense name — must be rejected (constraint 009)
    st, _, raw = safe_request("PUT", f"/collections/{COLL}/points?wait=true",
        json={"points": [{"id": 3, "vectors": {"v": {"indices": [0, 2], "values": [0.5, 0.7]}}}]})
    print(f"upsert sparse-on-dense-name: {st} {raw[:300]}")
    if st in (200, 201):
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — sparse vector accepted under dense name 'v' (name collision)")
        sys.exit(1)
    if st >= 500:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — sparse collision upsert returned {st}")
        sys.exit(1)

    # rejected writes must not partially commit
    c1 = count_exact()
    if c1 != 1:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — rejected upserts leaked into state: count={c1}")
        sys.exit(1)

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
