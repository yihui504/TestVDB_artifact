# script_id: state_collections_delete_003
# strategy: delete_consistency
# endpoint: collections+delete
# Attack: qdrant_bc_collection_delete_isolation_001 (behavioral contract, 本块第 2 单元)
#   覆盖: two collections with points; delete one => deleted GET 404; other count unchanged
#   强化: 两集合使用完全相同的 point ids + 区分 payload，删除 A 后 B 的同 id 点必须原样保留（数据不串）
# constraint_ids: qdrant_bc_collection_delete_isolation_001, qdrant_state_collections_delete_001,
#   qdrant_inv_count_after_upsert_001, qdrant_inv_collection_gone_after_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned)
"""
State: A and B both hold the SAME 6 point ids (0..5) with distinguishing payloads
({"owner":"a"} vs {"owner":"b"}). DELETE A. Then B must be fully intact:
  - exact count == 6 (unchanged)
  - batch get all 6 ids returns 6 points, every payload owner == "b" (no data bleed)
  - scroll returns exactly 6 points, all owner == "b"
  - filtered count (must owner=b) == 6
And A must be gone: GET 404, count 404. Any B-side deviation = Type4; any 5xx = Type3.
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
COLL_A = f"st_cdel_iso_a_{TS}"
COLL_B = f"st_cdel_iso_b_{TS}"
DIM = 4
N = 6

def cleanup():
    for name in (COLL_A, COLL_B):
        try:
            safe_request("DELETE", f"/collections/{name}")
        except Exception:
            pass

def defect(msg):
    print(msg)
    print("VERDICT: DEFECT_FOUND")
    sys.exit(1)

def count_exact(name, flt=None):
    payload = {"exact": True}
    if flt is not None:
        payload["filter"] = flt
    st, body, raw = safe_request("POST", f"/collections/{name}/points/count", json=payload)
    print(f"count[{name}]: {st} {raw[:200]}")
    if st != 200 or not isinstance(body, dict):
        return st, None
    r = body.get("result")
    return st, (r.get("count") if isinstance(r, dict) else None)

try:
    # setup: A and B with identical ids, distinguishing payloads
    for name, owner in ((COLL_A, "a"), (COLL_B, "b")):
        st, _, raw = safe_request("PUT", f"/collections/{name}",
                                  json={"vectors": {"size": DIM, "distance": "Cosine"}})
        print(f"create {name}: {st} {raw[:150]}")
        if st not in (200, 201):
            print("VERDICT: SCRIPT_ERROR")
            sys.exit(2)
        pts = [{"id": i, "vector": [0.1 * (i + 1)] * DIM, "payload": {"owner": owner}} for i in range(N)]
        st, _, raw = safe_request("PUT", f"/collections/{name}/points?wait=true", json={"points": pts})
        print(f"upsert {name}: {st} {raw[:150]}")
        if st not in (200, 201):
            print("VERDICT: SCRIPT_ERROR")
            sys.exit(2)
    for name in (COLL_A, COLL_B):
        _, c = count_exact(name)
        if c != N:
            defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — pre-delete count {name} expected {N}, got {c}")

    # delete A (behavioral contract scenario)
    st, _, raw = safe_request("DELETE", f"/collections/{COLL_A}")
    print(f"delete A: {st} {raw[:200]}")
    if st not in (200, 201):
        print(f"OBSERVATION: DELETE A returned {st}; continuing isolation checks")

    # A must be gone
    st, _, raw = safe_request("GET", f"/collections/{COLL_A}")
    print(f"get A after delete: {st} {raw[:200]}")
    if st == 200:
        defect("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — GET deleted A returned 200 (zombie)")
    if st >= 500 or st == 0:
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — GET deleted A got {st}: {raw[:150]}")
    st, _ = count_exact(COLL_A)
    if st == 200:
        defect("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — count on deleted A returned 200 (zombie)")
    if st >= 500 or st == 0:
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — count on deleted A got {st}")

    # B must be fully intact (twice, stability check)
    for round_i in range(2):
        _, c = count_exact(COLL_B)
        if c != N:
            defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — sibling B count changed after deleting A: expected {N}, got {c} (round {round_i})")

    # batch get on B: all 6 ids present with owner=b
    st, body, raw = safe_request("POST", f"/collections/{COLL_B}/points/get",
                                 json={"ids": list(range(N)), "with_payload": True})
    print(f"batch get B: {st} {raw[:300]}")
    if st != 200 or not isinstance(body, dict):
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — batch get B returned {st}: {raw[:150]}")
    got = body.get("result")
    if not isinstance(got, list):
        defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — batch get B result not a list: {raw[:150]}")
    if len(got) != N:
        defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — batch get B returned {len(got)} points, expected {N}")
    for p in got:
        owner = (p.get("payload") or {}).get("owner")
        if owner != "b":
            defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — B point {p.get('id')} payload owner={owner}, expected 'b' (data bleed from A)")

    # scroll B: exactly N points, all owner=b
    st, body, raw = safe_request("POST", f"/collections/{COLL_B}/points/scroll",
                                 json={"limit": 20, "with_payload": True})
    print(f"scroll B: {st} {raw[:300]}")
    if st == 200 and isinstance(body, dict):
        pts_b = body.get("result", {})
        pts_b = pts_b.get("points") if isinstance(pts_b, dict) else pts_b
        if isinstance(pts_b, list):
            if len(pts_b) != N:
                defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — scroll B returned {len(pts_b)} points, expected {N}")
            for p in pts_b:
                if (p.get("payload") or {}).get("owner") != "b":
                    defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — scroll B found non-b payload: {json.dumps(p)[:150]}")
    elif st >= 500 or st == 0:
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — scroll B got {st}: {raw[:150]}")

    # filtered count on B (exact=true，避开 approximate estimator by-design)
    _, c = count_exact(COLL_B, flt={"must": [{"key": "owner", "match": {"value": "b"}}]})
    if c != N:
        defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — filtered count owner=b on B expected {N}, got {c}")

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
