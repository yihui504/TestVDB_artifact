# script_id: semantic_collections_delete_004
# strategy: search_correctness
# endpoint: collections+delete
# Attack: qdrant_bc_collection_delete_isolation_001 search-semantics slice (survivor's search AND
#         query results — id ordering and scores — must be identical before/after an unrelated
#         collection delete; vectors chosen tie-free to avoid by-design HNSW tie non-determinism)
# constraint_ids: qdrant_bc_collection_delete_isolation_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-05 semantic contract (isolation of search semantics)
# Block: chunk_collections+delete
"""Search-semantic correctness under the isolation contract: 'other
collections unaffected' must include their SEARCH semantics. Capture the
survivor's ranking (ids + scores) via both legacy /points/search and universal
/points/query before and after deleting an unrelated collection; any drift in
ordering or scores > 1e-6 is Type4. Vectors are picked so cosine similarities
are distinct (no ties), steering clear of the documented by-design HNSW
tie-breaking non-determinism."""
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


def ranking(name, api):
    """Return ordered [(id, score)] via search or query API, or None on failure."""
    if api == "search":
        s, body, raw = safe_request("POST", f"/collections/{name}/points/search",
                                    {"vector": QUERY, "limit": 3})
        res = body.get("result", []) if isinstance(body, dict) else []
    else:
        s, body, raw = safe_request("POST", f"/collections/{name}/points/query",
                                    {"query": QUERY, "limit": 3})
        node = body.get("result", {}) if isinstance(body, dict) else {}
        res = node.get("points", []) if isinstance(node, dict) else []
    print(f"{api} {name}: {s} {raw[:250]}")
    if s != 200:
        return None
    return [(r.get("id"), r.get("score")) for r in res]


QUERY = [1.0, 0.1, 0.0, 0.0]
# tie-free cosine similarities vs QUERY: ~0.9950 / ~0.0995 / ~0.0286
SURVIVOR_POINTS = [
    {"id": 1, "vector": [1.0, 0.1, 0.0, 0.0]},
    {"id": 2, "vector": [0.0, 1.0, 0.0, 0.0]},
    {"id": 3, "vector": [0.0, 0.3, 1.0, 0.0]},
]
A = f"sem_del_ss_a_{TS}"
B = f"sem_del_ss_b_{TS}"
try:
    for name, pts in ((A, [{"id": 1, "vector": [0.5, 0.5, 0.5, 0.5]},
                           {"id": 2, "vector": [0.4, 0.4, 0.4, 0.4]}]),
                      (B, SURVIVOR_POINTS)):
        s, _, raw = safe_request("PUT", f"/collections/{name}",
                                 {"vectors": {"size": 4, "distance": "Cosine"}})
        if s not in (200, 201):
            print(f"VERDICT: SCRIPT_ERROR — create {name}: {s} {raw[:150]}")
            sys.exit(2)
        s, _, raw = safe_request("PUT", f"/collections/{name}/points?wait=true",
                                 {"points": pts})
        print(f"insert {name}: {s} {raw[:120]}")
        if s != 200:
            print(f"VERDICT: SCRIPT_ERROR — insert {name}: {s}")
            sys.exit(2)
    time.sleep(1.0)  # let indexing settle before baseline capture

    pre_search = ranking(B, "search")
    pre_query = ranking(B, "query")
    if not pre_search or not pre_query:
        print("VERDICT: SCRIPT_ERROR — baseline search/query failed")
        sys.exit(2)
    print(f"baseline search: {pre_search}")
    print(f"baseline query : {pre_query}")
    if [i for i, _ in pre_search] != [1, 2, 3]:
        print("VERDICT: SCRIPT_ERROR — baseline ordering unexpected "
              f"{[i for i, _ in pre_search]}; tie-free setup assumption broken")
        sys.exit(2)

    s, _, raw = safe_request("DELETE", f"/collections/{A}")
    print(f"delete {A}: {s} {raw[:150]}")
    if s != 200:
        print(f"VERDICT: SCRIPT_ERROR — delete returned {s}")
        sys.exit(2)

    post_search = ranking(B, "search")
    post_query = ranking(B, "query")
    if not post_search or not post_query:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print("survivor search/query FAILED after unrelated collection delete")
        sys.exit(1)

    for api, pre, post in (("search", pre_search, post_search),
                           ("query", pre_query, post_query)):
        pre_ids = [i for i, _ in pre]
        post_ids = [i for i, _ in post]
        if pre_ids != post_ids:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"{api} ordering drifted after unrelated delete: "
                  f"{pre_ids} -> {post_ids}")
            sys.exit(1)
        for (pid, sc1), (_, sc2) in zip(pre, post):
            if sc1 is None or sc2 is None or abs(sc1 - sc2) > 1e-6:
                print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
                print(f"{api} score drift for id={pid}: {sc1} -> {sc2}")
                sys.exit(1)
    # survivor count unchanged (contract clause)
    s, body, raw = safe_request("POST", f"/collections/{B}/points/count",
                                {"exact": True})
    n = body.get("result", {}).get("count") if isinstance(body, dict) else None
    print(f"count {B} post: {s} count={n}")
    if s != 200 or n != 3:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"survivor count {n} != 3 after unrelated delete")
        sys.exit(1)
    print(f"post search: {post_search}")
    print(f"post query : {post_query}")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)
finally:
    cleanup(A)
    cleanup(B)
