# script_id: state_collections_create_001
# strategy: state_transition (模式 B 重复创建)
# endpoint: collections+create
# Attack: qdrant_state_collections_create_001 (重复创建冲突) + qdrant_inv_collection_visible_after_create_001
#   (策略2/模式B × collections+create)
# constraint_ids: qdrant_state_collections_create_001, qdrant_inv_collection_visible_after_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-03 Concurrency State Blindness (collection 级状态转换)
"""
State: create collection with dim 4 -> insert 2 points -> create SAME name again.
Expected: second create rejected with 4xx conflict (409/400), NOT overwrite and NOT 500.
After rejection: collection still exists, count still 2, data intact.
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
COLL = f"st_cc_dup_{TS}"
CREATE_PATH = "/collections/{name}"
UPSERT_PATH = "/collections/{name}/points?wait=true"
COUNT_PATH = "/collections/{name}/points/count"
BODY = {"vectors": {"size": 4, "distance": "Cosine"}}

def cleanup():
    try:
        safe_request("DELETE", CREATE_PATH.format(name=COLL))
    except Exception:
        pass

try:
    st, body, raw = safe_request("PUT", CREATE_PATH.format(name=COLL), json=BODY)
    print(f"create#1: {st} {raw[:200]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)

    st, _, raw = safe_request("PUT", UPSERT_PATH.format(name=COLL), json={
        "points": [
            {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]},
            {"id": 2, "vector": [0.4, 0.3, 0.2, 0.1]},
        ]})
    print(f"upsert: {st} {raw[:200]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)

    # duplicate create — must be rejected, not overwrite, not 500
    st, _, raw = safe_request("PUT", CREATE_PATH.format(name=COLL), json=BODY)
    print(f"create#2 (duplicate): {st} {raw[:300]}")
    if st == 500 or st == 0:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — duplicate create returned {st}")
        sys.exit(1)
    if st in (200, 201):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — duplicate create silently accepted (overwrite?)")
        sys.exit(1)

    # data must be intact after rejected duplicate create
    time.sleep(1)
    st, body, raw = safe_request("POST", COUNT_PATH.format(name=COLL), json={"exact": True})
    print(f"count: {st} {raw[:200]}")
    cnt = None
    try:
        cnt = body["result"]["count"]
    except (TypeError, KeyError):
        pass
    if st != 200 or cnt != 2:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — data corrupted after duplicate create rejection: count={cnt}")
        sys.exit(1)

    # visibility invariant: GET still 200 with status field
    st, body, raw = safe_request("GET", CREATE_PATH.format(name=COLL))
    print(f"get: {st} {raw[:200]}")
    try:
        cstatus = body["result"]["status"]
    except (TypeError, KeyError):
        cstatus = None
    if st != 200 or cstatus not in ("green", "yellow", "red"):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — collection not visible/intact after duplicate create: status={cstatus}")
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
