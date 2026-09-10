# script_id: state_collections_delete_002
# strategy: delete_consistency
# endpoint: collections+delete
# Attack: qdrant_state_collections_delete_001 × 模式A(创建→修改→删除→恢复)
#   覆盖: delete => 200 后 upsert/count 必须 404；同名 recreate 必须 200 且 count==0（无僵尸数据复活）
# constraint_ids: qdrant_state_collections_delete_001, qdrant_inv_collection_gone_after_delete_001,
#   qdrant_inv_count_after_upsert_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned)
"""
State: create collection, upsert 5 points, DELETE (200), then:
  1. write to deleted collection (upsert) must 404 — 200 = zombie write, 5xx = runtime failure
  2. count on deleted collection must 404 — 200 = zombie read
  3. recreate SAME name must succeed (200) — 409 = delete not fully applied (state machine stuck)
  4. after recreate, exact count must be 0 — old points reappearing = data resurrection (Type4)
  5. old point id must 404 via point+get
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
COLL = f"st_cdel_zomb_{TS}"
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

def count_exact(name):
    st, body, raw = safe_request("POST", f"/collections/{name}/points/count", json={"exact": True})
    print(f"count[{name}]: {st} {raw[:200]}")
    if st != 200 or not isinstance(body, dict):
        return st, None
    r = body.get("result")
    return st, (r.get("count") if isinstance(r, dict) else None)

try:
    # phase 1: create + seed 5 points
    st, _, raw = safe_request("PUT", f"/collections/{COLL}",
                              json={"vectors": {"size": DIM, "distance": "Cosine"}})
    print(f"create: {st} {raw[:150]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)
    pts = [{"id": i, "vector": [0.2 * (i + 1)] * DIM, "payload": {"gen": 1}} for i in range(5)]
    st, _, raw = safe_request("PUT", f"/collections/{COLL}/points?wait=true", json={"points": pts})
    print(f"upsert gen1: {st} {raw[:150]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)
    _, c = count_exact(COLL)
    if c != 5:
        defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — seed count expected 5, got {c}")

    # phase 2: delete
    st, _, raw = safe_request("DELETE", f"/collections/{COLL}")
    print(f"delete: {st} {raw[:200]}")
    if st not in (200, 201):
        print(f"OBSERVATION: DELETE returned {st}; proceeding with post-delete state checks")

    # phase 3: write to deleted collection
    st, _, raw = safe_request("PUT", f"/collections/{COLL}/points?wait=true",
                              json={"points": [{"id": 99, "vector": [0.1] * DIM}]})
    print(f"upsert to deleted: {st} {raw[:200]}")
    if st == 200:
        defect("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — upsert to DELETED collection returned 200 (zombie write)")
    if st >= 500 or st == 0:
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — upsert to deleted got {st}: {raw[:150]}")

    # phase 4: count on deleted collection
    st, c = count_exact(COLL)
    if st == 200:
        defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — count on DELETED collection returned 200 count={c} (zombie)")
    if st >= 500 or st == 0:
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — count on deleted got {st}")

    # phase 5: recreate same name — must succeed cleanly
    st, _, raw = safe_request("PUT", f"/collections/{COLL}",
                              json={"vectors": {"size": DIM, "distance": "Cosine"}})
    print(f"recreate: {st} {raw[:200]}")
    if st == 409:
        defect("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — recreate after DELETE 200 failed 409 (delete not applied)")
    if st not in (200, 201):
        defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — recreate returned {st}: {raw[:150]}")

    time.sleep(0.5)
    # phase 6: resurrection check — count must be 0, old ids must be gone
    st, c = count_exact(COLL)
    if c is None:
        defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — count after recreate not readable (status {st})")
    if c != 0:
        defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — recreated collection has {c} points, expected 0 (data resurrection)")
    st, _, raw = safe_request("GET", f"/collections/{COLL}/points/0")
    print(f"get old point: {st} {raw[:200]}")
    if st == 200:
        defect("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — old point id 0 retrievable after delete+recreate (resurrection)")
    if st >= 500 or st == 0:
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — get point on recreated collection got {st}: {raw[:150]}")

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
