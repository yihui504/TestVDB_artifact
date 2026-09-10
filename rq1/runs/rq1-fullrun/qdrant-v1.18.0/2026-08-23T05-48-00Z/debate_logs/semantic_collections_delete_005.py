# script_id: semantic_collections_delete_005
# strategy: behavioral_contract
# endpoint: collections+delete
# Attack: "Drop the collection and ALL of its data" fidelity (endpoint description) x
#         qdrant_bc_collection_delete_isolation_001 / qdrant_inv_collection_gone_after_delete_001 —
#         delete then recreate same name must yield a virgin collection: count 0, scroll empty,
#         old points 404, old payload index gone (no data/index resurrection)
# constraint_ids: qdrant_bc_collection_delete_isolation_001, qdrant_inv_collection_gone_after_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-03 Concurrency State Blindness (state residue across delete/recreate boundary)
# Block: chunk_collections+delete
"""Data-resurrection probe: contract says delete drops the collection and all
of its data. The strongest semantic test of that clause is delete -> recreate
with the SAME name: every artifact of the old life (points, payloads, payload
indexes) must be gone. Any old point readable, non-zero count, non-empty
scroll, or old index name surviving in the fresh describe is Type4."""
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


C = f"sem_del_resh_{TS}"
IDX_FIELD = f"city_{TS[-5:]}"  # unique field name — text search cannot false-positive
try:
    s, _, raw = safe_request("PUT", f"/collections/{C}",
                             {"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"create: {s} {raw[:150]}")
    if s not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — create: {s}")
        sys.exit(2)
    s, _, raw = safe_request("PUT", f"/collections/{C}/index/{IDX_FIELD}?wait=true",
                             {"field_schema": "keyword"})
    print(f"create index {IDX_FIELD}: {s} {raw[:150]}")
    if s not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — index create: {s}")
        sys.exit(2)
    pts = [{"id": i, "vector": [0.1 * i, 0.2, 0.3, 0.4],
            "payload": {IDX_FIELD: f"city{i}"}} for i in range(1, 6)]
    s, _, raw = safe_request("PUT", f"/collections/{C}/points?wait=true",
                             {"points": pts})
    print(f"insert 5 pts: {s} {raw[:120]}")
    if s != 200:
        print(f"VERDICT: SCRIPT_ERROR — insert: {s}")
        sys.exit(2)
    s, body, raw = safe_request("POST", f"/collections/{C}/points/count",
                                {"exact": True})
    n = body.get("result", {}).get("count") if isinstance(body, dict) else None
    print(f"count pre-delete: {s} count={n}")
    if s != 200 or n != 5:
        print(f"VERDICT: SCRIPT_ERROR — sanity count: {s} n={n}")
        sys.exit(2)

    s, _, raw = safe_request("DELETE", f"/collections/{C}")
    print(f"delete: {s} {raw[:150]}")
    if s != 200:
        print(f"VERDICT: SCRIPT_ERROR — delete returned {s}")
        sys.exit(2)
    s, _, raw = safe_request("GET", f"/collections/{C}")
    print(f"describe after delete: {s} {raw[:150]}")
    if s != 404:
        print(f"VERDICT: SCRIPT_ERROR — expected 404 after delete, got {s}")
        sys.exit(2)

    # recreate with the same name — must be a virgin collection
    s, _, raw = safe_request("PUT", f"/collections/{C}",
                             {"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"recreate: {s} {raw[:150]}")
    if s not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — recreate: {s}")
        sys.exit(2)

    s, body, raw = safe_request("POST", f"/collections/{C}/points/count",
                                {"exact": True})
    n = body.get("result", {}).get("count") if isinstance(body, dict) else None
    print(f"count after recreate: {s} count={n}")
    if s == 200 and n not in (0, None):
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"recreated collection resurrected {n} old points — delete did "
              "not drop 'all of its data'")
        sys.exit(1)

    s, body, raw = safe_request("POST", f"/collections/{C}/points/scroll",
                                {"limit": 100, "with_payload": True})
    points = (body.get("result", {}) or {}).get("points", []) \
        if isinstance(body, dict) else []
    print(f"scroll after recreate: {s} n={len(points)} {raw[:200]}")
    if s == 200 and points:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"recreated collection scroll returned {len(points)} old points")
        sys.exit(1)

    s, _, raw = safe_request("GET", f"/collections/{C}/points/3")
    print(f"get old point 3: {s} {raw[:150]}")
    if s == 200:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print("old point resurrected and readable after delete+recreate")
        sys.exit(1)

    # old payload index must not survive into the fresh collection
    s, _, raw = safe_request("GET", f"/collections/{C}")
    idx_resurrected = s == 200 and IDX_FIELD in raw
    print(f"describe fresh: {s} index_field_present={idx_resurrected} {raw[:250]}")
    if idx_resurrected:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"payload index on {IDX_FIELD} survived delete+recreate")
        sys.exit(1)

    s, body, raw = safe_request("POST", f"/collections/{C}/points/search",
                                {"vector": [0.1, 0.2, 0.3, 0.4], "limit": 10})
    res = body.get("result", []) if isinstance(body, dict) else []
    print(f"search after recreate: {s} n={len(res)}")
    if s == 200 and res:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"search on recreated collection returned {len(res)} old points")
        sys.exit(1)
    print("VERDICT: NO_DEFECT")
    sys.exit(0)
finally:
    cleanup(C)
