# script_id: semantic_collections_delete_003
# strategy: behavioral_contract
# endpoint: collections+delete
# Attack: qdrant_bc_collection_delete_isolation_001 canonical scenario (two collections with points;
#         delete one => deleted GET 404, survivor count unchanged, scroll payloads intact,
#         per-point get + search on survivor still work)
# constraint_ids: qdrant_bc_collection_delete_isolation_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-05 semantic contract (cross-collection isolation)
# Block: chunk_collections+delete
"""Behavioral contract qdrant_bc_collection_delete_isolation_001:
scenario 'two collections with points; delete one' expects 'deleted collection
GET => 404; other collection count unchanged'. This script executes the exact
canonical scenario and additionally verifies the survivor's payloads, point
access and search — the contract's 'other collections unaffected' clause.
Self-contained transport: qdrant REST via safe_request."""
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


A = f"sem_del_iso_a_{TS}"
B = f"sem_del_iso_b_{TS}"
VEC = [0.1, 0.2, 0.3, 0.4]
try:
    for name, tag in ((A, "a"), (B, "b")):
        s, _, raw = safe_request("PUT", f"/collections/{name}",
                                 {"vectors": {"size": 4, "distance": "Cosine"}})
        print(f"create {name}: {s} {raw[:150]}")
        if s not in (200, 201):
            print(f"VERDICT: SCRIPT_ERROR — setup create {name}: {s}")
            sys.exit(2)
        pts = [{"id": i, "vector": [0.02 * i + 0.01, 0.2, 0.3, 0.4],
                "payload": {"coll": tag, "ord": i}} for i in (1, 2, 3)]
        s, _, raw = safe_request("PUT", f"/collections/{name}/points?wait=true",
                                 {"points": pts})
        print(f"insert 3 pts into {name}: {s} {raw[:120]}")
        if s != 200:
            print(f"VERDICT: SCRIPT_ERROR — setup insert {name}: {s}")
            sys.exit(2)

    # sanity: both counts = 3
    for name in (A, B):
        s, body, raw = safe_request("POST", f"/collections/{name}/points/count",
                                    {"exact": True})
        n = body.get("result", {}).get("count") if isinstance(body, dict) else None
        print(f"count {name} pre: {s} count={n}")
        if s != 200 or n != 3:
            print(f"VERDICT: SCRIPT_ERROR — sanity count {name}: {s} {raw[:150]}")
            sys.exit(2)

    # contract action: delete A
    s, _, raw = safe_request("DELETE", f"/collections/{A}")
    print(f"delete {A}: {s} {raw[:150]}")
    if s != 200:
        print(f"VERDICT: SCRIPT_ERROR — delete returned {s} (status contract "
              "covered by semantic_collections_delete_001)")
        sys.exit(2)

    # 1. deleted collection GET => 404
    s, _, raw = safe_request("GET", f"/collections/{A}")
    print(f"describe {A} after delete: {s} {raw[:150]}")
    if s == 200:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"deleted collection {A} still readable (200)")
        sys.exit(1)
    if s != 404:
        print(f"VERDICT: SCRIPT_ERROR — describe status {s}")
        sys.exit(2)

    # 2. other collection count unchanged (contract clause)
    s, body, raw = safe_request("POST", f"/collections/{B}/points/count",
                                {"exact": True})
    n = body.get("result", {}).get("count") if isinstance(body, dict) else None
    print(f"count {B} post: {s} count={n}")
    if s != 200 or n != 3:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"survivor count changed after unrelated delete: {n} != 3")
        sys.exit(1)

    # 3. survivor payloads intact via scroll
    s, body, raw = safe_request("POST", f"/collections/{B}/points/scroll",
                                {"limit": 10, "with_payload": True})
    print(f"scroll {B}: {s} {raw[:300]}")
    points = (body.get("result", {}) or {}).get("points", []) \
        if isinstance(body, dict) else []
    by_id = {p.get("id"): p.get("payload", {}) for p in points}
    if set(by_id) != {1, 2, 3}:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"survivor scroll ids {sorted(by_id)} != [1,2,3] after unrelated delete")
        sys.exit(1)
    for i in (1, 2, 3):
        if by_id[i].get("coll") != "b" or by_id[i].get("ord") != i:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"survivor payload corrupted for id={i}: {by_id[i]}")
            sys.exit(1)

    # 4. per-point access on survivor
    s, _, raw = safe_request("GET", f"/collections/{B}/points/2")
    print(f"get_point {B}/2: {s} {raw[:150]}")
    if s != 200:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"survivor point access broken after unrelated delete: {s}")
        sys.exit(1)

    # 5. search on survivor still returns all its points
    s, body, raw = safe_request("POST", f"/collections/{B}/points/search",
                                {"vector": VEC, "limit": 3, "with_payload": True})
    res = body.get("result", []) if isinstance(body, dict) else []
    print(f"search {B}: {s} ids={[r.get('id') for r in res]}")
    if s != 200 or len(res) != 3:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"survivor search returned {len(res)} of 3 after unrelated delete")
        sys.exit(1)
    print("VERDICT: NO_DEFECT")
    sys.exit(0)
finally:
    cleanup(A)
    cleanup(B)
