# script_id: state_collections_create_005
# strategy: state_transition (模式 C 依赖链断裂 — drop 后 index/数据残留)
# endpoint: collections+create
# Attack: qdrant_state_collections_create_001 + 依赖链：create → upsert → drop → recreate 同名
#   验证 recreate 后是全新状态（无旧点残留、无 500）
# constraint_ids: qdrant_state_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-03 Concurrency State Blindness (状态残留)
"""
Sequence: create → insert 3 points → delete collection → recreate SAME name
with same config → count must be 0 (no resurrection of old points), no 500,
describe status valid. Verifies drop is a complete state reset (cf. WAL
resurrection issues in threat model).
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
COLL = f"st_cc_recreate_{TS}"
BODY = {"vectors": {"size": 4, "distance": "Cosine"}}

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
    st, _, raw = safe_request("PUT", f"/collections/{COLL}", json=BODY)
    print(f"create#1: {st} {raw[:150]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)

    st, _, raw = safe_request("PUT", f"/collections/{COLL}/points?wait=true", json={
        "points": [{"id": i, "vector": [0.1 * i, 0.2, 0.3, 0.4]} for i in (1, 2, 3)]})
    print(f"upsert: {st} {raw[:150]}")
    c0 = count_exact()
    if c0 != 3:
        print(f"VERDICT: SCRIPT_ERROR — baseline count {c0} != 3, cannot proceed")
        sys.exit(2)

    st, _, raw = safe_request("DELETE", f"/collections/{COLL}")
    print(f"drop: {st} {raw[:150]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)

    # after drop, operations must give clean 404 (not 500)
    st, _, raw = safe_request("POST", f"/collections/{COLL}/points/count", json={"exact": True})
    print(f"count-after-drop: {st} {raw[:150]}")
    if st >= 500 or st == 0:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — count on dropped collection returned {st}")
        sys.exit(1)
    if st != 404:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — dropped collection count returned {st}, expected 404")
        sys.exit(1)

    # recreate same name — fresh state expected
    st, _, raw = safe_request("PUT", f"/collections/{COLL}", json=BODY)
    print(f"create#2: {st} {raw[:150]}")
    if st >= 500 or st == 0:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — recreate after drop returned {st}")
        sys.exit(1)
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)

    time.sleep(1)
    c1 = count_exact()
    if c1 is None or c1 != 0:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — old points resurrected after recreate: count={c1}")
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
