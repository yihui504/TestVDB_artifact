# script_id: semantic_collections_create_020
# strategy: behavioral_contract
# endpoint: collections+create
# Attack: qdrant_bc_create_query_visibility_001 (create collection -> upsert with wait=true -> query nearest with same vector: upserted point MUST be top hit with distance ~0 / score ~1.0, ranked above near-miss and opposite distractors; queried IMMEDIATELY, no sleep)
# constraint_ids: qdrant_bc_create_query_visibility_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points
# doc_version: 1.18.x (versioned)
# Blindspot: BS-04/BS-05 (wait=true durability-visibility contract)
# Block: chunk_collections+create-2of2
"""Behavioral contract (explicit): points visible to search/retrieve after
upsert with wait=true. Chain: create (Cosine dim 4) -> upsert 3 points with
?wait=true (target exact vector, near-miss, opposite) -> IMMEDIATELY query
nearest with the target vector. Contract: top hit = target id with distance
~0 (cosine score ~1.0), no sleep/retry allowed. A wait=true upsert that is
not immediately queryable violates the strongest visibility guarantee
(Type4). Self-contained transport: qdrant REST via safe_request (no runtime
module); paths from contract: PUT /collections/{n}, PUT /collections/{n}/points?wait=true,
POST /collections/{n}/points/query."""
import os, sys, time, json, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)
AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")
EPS = 1e-3
TS = str(int(time.time()))
COLL = f"sem_vis_{TS}"


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


def cleanup():
    try:
        safe_request("DELETE", f"/collections/{COLL}")
    except Exception:
        pass


try:
    s, _, raw = safe_request("PUT", f"/collections/{COLL}",
        {"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"setup create -> {s} {raw[:200]}")
    if s not in (200, 201):
        print("VERDICT: SCRIPT_ERROR — setup failed")
        sys.exit(2)

    v_target = [0.9, 0.1, 0.1, 0.1]
    v_near = [0.8, 0.2, 0.1, 0.1]
    v_opposite = [-0.9, -0.1, -0.1, -0.1]
    status, body, raw = safe_request("PUT", f"/collections/{COLL}/points?wait=true",
        {"points": [
            {"id": 100, "vector": v_target},
            {"id": 200, "vector": v_near},
            {"id": 300, "vector": v_opposite},
        ]})
    print(f"upsert wait=true -> {status} {raw[:300]}")
    if status not in (200, 201):
        print("VERDICT: SCRIPT_ERROR — wait=true upsert failed")
        sys.exit(2)

    # IMMEDIATE query — no sleep, no retry: wait=true guarantees visibility
    s, _, raw = safe_request("POST", f"/collections/{COLL}/points/query",
        {"query": v_target, "limit": 3})
    print(f"query nearest -> {s} {raw[:400]}")
    if s != 200:
        print("VERDICT: SCRIPT_ERROR — query failed")
        sys.exit(2)
    try:
        res = json.loads(raw).get("result", [])
    except Exception:
        print("VERDICT: SCRIPT_ERROR — query response unparseable")
        sys.exit(2)
    if not res:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print("upsert wait=true returned 200 but immediate query returns 0 points "
              "— visibility contract violated")
        sys.exit(1)
    top = res[0]
    top_id, top_score = top.get("id"), top.get("score")
    print(f"top hit id={top_id} score={top_score}")
    if top_id != 100:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"nearest query for an exact stored vector must top-hit id=100; got {top_id!r}")
        sys.exit(1)
    if top_score is None or abs(top_score - 1.0) > EPS:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"identical-vector query must have cosine score ~1.0 (distance ~0); got {top_score}")
        sys.exit(1)
    ids = [r.get("id") for r in res]
    if 300 in ids[:2]:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"opposite vector ranked in top-2 for the query: order {ids}")
        sys.exit(1)
    print(f"rank order {ids} (contract: 100 first, 300 last)")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)
finally:
    cleanup()
