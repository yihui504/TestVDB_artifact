# script_id: state_collections_delete_008
# strategy: index_state
# endpoint: collections+delete
# Attack: qdrant_state_collections_delete_001 × 模式C 依赖链断裂 (payload index -> collection)
#   覆盖: delete collection 后 index+create 必须 404（200 = 僵尸成功 Type1）；
#   index+delete 在已删集合上 404 合理 / 200 幂等只记 OBSERVATION（qdrant_state_index_delete_001 幂等语义）；
#   同名 recreate 后 payload_schema 不得残留旧 index（残留 = Type4 schema 复活）；
#   recreate 后 index+create 可正常成功
# constraint_ids: qdrant_state_collections_delete_001, qdrant_inv_collection_gone_after_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned)
"""
Index lifecycle vs collection delete: build a keyword payload index, delete the
collection, then verify the index subsystem agrees the collection is gone, and
that a same-name recreate starts with a clean payload_schema.
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
COLL = f"st_cdel_idx_{TS}"
FIELD = "city"
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

def payload_schema_names():
    st, body, raw = safe_request("GET", f"/collections/{COLL}")
    print(f"get collection: {st} {raw[:250]}")
    if st != 200 or not isinstance(body, dict):
        return st, None
    res = body.get("result") or {}
    schema = (res.get("config") or {}).get("payload_schema") or {}
    return st, set(schema.keys())

try:
    # phase 1: create + points + keyword index
    st, _, raw = safe_request("PUT", f"/collections/{COLL}",
                              json={"vectors": {"size": DIM, "distance": "Cosine"}})
    print(f"create: {st} {raw[:150]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)
    pts = [{"id": i, "vector": [0.1 * (i + 1)] * DIM, "payload": {FIELD: f"c{i % 3}"}} for i in range(6)]
    st, _, raw = safe_request("PUT", f"/collections/{COLL}/points?wait=true", json={"points": pts})
    print(f"upsert: {st} {raw[:150]}")
    st, _, raw = safe_request("PUT", f"/collections/{COLL}/index?wait=true",
                              json={"field_name": FIELD, "field_schema": "keyword"})
    print(f"create index: {st} {raw[:200]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)
    time.sleep(0.5)
    st, names = payload_schema_names()
    if names is None or FIELD not in names:
        print(f"OBSERVATION: field index not visible in payload_schema (got {names})")

    # phase 2: delete collection
    st, _, raw = safe_request("DELETE", f"/collections/{COLL}")
    print(f"delete: {st} {raw[:200]}")
    if st not in (200, 201):
        print(f"OBSERVATION: DELETE returned {st}; continuing")

    # phase 3: index+create on deleted collection must NOT succeed
    st, _, raw = safe_request("PUT", f"/collections/{COLL}/index?wait=true",
                              json={"field_name": FIELD, "field_schema": "keyword"})
    print(f"index+create on deleted: {st} {raw[:200]}")
    if st == 200:
        defect("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — index+create succeeded on DELETED collection (zombie schema write)")
    if st >= 500 or st == 0:
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — index+create on deleted got {st}: {raw[:150]}")

    # phase 4: index+delete on deleted collection — 404 expected, 200 tolerated as idempotent
    st, _, raw = safe_request("DELETE", f"/collections/{COLL}/index/{FIELD}")
    print(f"index+delete on deleted: {st} {raw[:200]}")
    if st == 200:
        print("OBSERVATION: index+delete returned 200 on deleted collection (idempotent per qdrant_state_index_delete_001) — not scored")
    if st >= 500 or st == 0:
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — index+delete on deleted got {st}: {raw[:150]}")

    # phase 5: recreate same name — payload_schema must be clean (no index resurrection)
    st, _, raw = safe_request("PUT", f"/collections/{COLL}",
                              json={"vectors": {"size": DIM, "distance": "Cosine"}})
    print(f"recreate: {st} {raw[:150]}")
    if st not in (200, 201):
        defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — recreate failed {st}: {raw[:150]}")
    time.sleep(0.5)
    st, names = payload_schema_names()
    if names is None:
        defect("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — recreated collection config unreadable")
    if FIELD in names:
        defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — old payload index '{FIELD}' resurrected in recreated collection: {names}")

    # phase 6: index subsystem healthy after churn — index+create must succeed now
    st, _, raw = safe_request("PUT", f"/collections/{COLL}/index?wait=true",
                              json={"field_name": FIELD, "field_schema": "keyword"})
    print(f"index+create after recreate: {st} {raw[:200]}")
    if st not in (200, 201):
        defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — index+create on healthy recreated collection failed {st}: {raw[:150]}")

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
