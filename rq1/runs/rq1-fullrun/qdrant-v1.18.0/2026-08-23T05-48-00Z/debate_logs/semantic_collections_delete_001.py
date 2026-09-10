# script_id: semantic_collections_delete_001
# strategy: behavioral_contract
# endpoint: collections+delete
# Attack: qdrant_state_collections_delete_001 full lifecycle (DELETE existing => 200; GET after => 404;
#         absent from list; DELETE again => 404; point access => 404)
# constraint_ids: qdrant_state_collections_delete_001, qdrant_inv_collection_gone_after_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-05 semantic contract (delete lifecycle state machine)
# Block: chunk_collections+delete
"""Behavioral contract (explicit, runtime-verified in contract): DELETE on an
existing collection => 200; DELETE on a missing collection => 404. After a 200
delete the collection must be fully gone: describe => 404, absent from
collections list, per-point access => 404. Any zombie readability is Type4.
NOTE: threat-model by-design "Idempotent DELETE returns 200 even if point
doesn't exist" covers POINTS-level delete; the COLLECTION-level contract here
explicitly asserts missing => 404, so a 200 on second DELETE is a violation.
Self-contained transport: qdrant REST via safe_request (no runtime module)."""
import os, sys, time, json, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)
AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")
TS = str(int(time.time()))


def safe_request(method, path, json_body=None, timeout=30):
    """(status, body, raw_text) triple — spec-mandated wrapper."""
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER
    try:
        resp = requests.request(method, url, headers=headers,
                                json=json_body, timeout=timeout)
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        return resp.status_code, body, resp.text
    except Exception as e:
        return -1, str(e), str(e)


def cleanup(name):
    try:
        safe_request("DELETE", f"/collections/{name}")
    except Exception:
        pass


C = f"sem_del_lc_{TS}"
try:
    s, _, raw = safe_request("PUT", f"/collections/{C}",
                             {"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"create: {s} {raw[:200]}")
    if s not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — setup create failed: {s}")
        sys.exit(2)
    pts = [{"id": i, "vector": [0.1 * i, 0.2, 0.3, 0.4]} for i in (1, 2, 3)]
    s, _, raw = safe_request("PUT", f"/collections/{C}/points?wait=true",
                             {"points": pts})
    print(f"insert 3 pts: {s} {raw[:150]}")
    if s != 200:
        print(f"VERDICT: SCRIPT_ERROR — setup insert failed: {s}")
        sys.exit(2)

    # 1. DELETE existing => must be 200 per contract
    s1, _, raw1 = safe_request("DELETE", f"/collections/{C}")
    print(f"delete#1 (existing): {s1} {raw1[:200]}")
    if s1 == 0 or 500 <= s1 <= 599:
        print("VERDICT: SCRIPT_ERROR — transport/server error on delete")
        sys.exit(2)
    if s1 != 200:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"contract asserts DELETE existing => 200, got {s1}")
        sys.exit(1)

    # 2. GET after delete => must be 404 (invariant qdrant_inv_collection_gone_after_delete_001)
    s2, _, raw2 = safe_request("GET", f"/collections/{C}")
    print(f"describe after delete: {s2} {raw2[:200]}")
    if s2 == 200:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print("collection still readable (200) after successful DELETE — zombie state")
        sys.exit(1)
    if s2 != 404:
        print(f"VERDICT: SCRIPT_ERROR — unexpected describe status {s2}")
        sys.exit(2)

    # 3. collections list must not contain the name
    s3, body3, raw3 = safe_request("GET", "/collections")
    print(f"list: {s3} {raw3[:200]}")
    names = []
    if s3 == 200 and isinstance(body3, dict):
        names = [c.get("name") for c in body3.get("result", {}).get("collections", [])]
    if C in names:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print("deleted collection still present in GET /collections list")
        sys.exit(1)

    # 4. per-point access on deleted collection => 404 (not 200 zombie)
    s4, _, raw4 = safe_request("GET", f"/collections/{C}/points/1")
    print(f"get_point after delete: {s4} {raw4[:200]}")
    if s4 == 200:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print("point of deleted collection still retrievable with 200")
        sys.exit(1)

    # 5. DELETE missing => must be 404 per explicit contract assertion
    s5, _, raw5 = safe_request("DELETE", f"/collections/{C}")
    print(f"delete#2 (missing): {s5} {raw5[:200]}")
    if s5 == 200:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print("contract asserts DELETE missing collection => 404, got 200 "
              "(collection-level contract; points-level idempotency is a separate by-design)")
        sys.exit(1)
    if s5 != 404:
        print(f"note: second delete returned {s5} (contract expects 404); "
              "flagged only 200 as hard violation, see above")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)
finally:
    cleanup(C)
