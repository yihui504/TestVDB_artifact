# script_id: semantic_collections_delete_009
# strategy: metamorphic
# endpoint: collections+delete
# Attack: async-write/delete/recreate state equivalence x "drop the collection and all of its data"
#         (endpoint description) — wait=false upserts racing a collection delete must never
#         resurrect into a same-named recreated collection (WAL/state-replay resurrection, BS-03)
# constraint_ids: qdrant_bc_collection_delete_isolation_001, qdrant_inv_collection_gone_after_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-03 Concurrency State Blindness (in-flight writes around delete)
# Block: chunk_collections+delete
# exploration_target: novel_candidate
"""Metamorphic state relation: state(delete after async writes; recreate name X)
must equal state(fresh create X) — i.e. a virgin collection. In-flight
(wait=false) upserts that raced the DELETE may succeed or fail (not judged),
but none of them may reappear in the recreated collection: delete drops 'all
of its data' and the new collection is a different object. Any of the original
ids resurfacing via count/scroll/get after the recreate is Type4 resurrection
(the WAL-replay hazard the threat model flags for BS-03)."""
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


E = f"sem_del_async_{TS}"
OLD_IDS = [1, 2, 3, 4, 5, 6, 7, 8, 9]
try:
    s, _, raw = safe_request("PUT", f"/collections/{E}",
                             {"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"create: {s} {raw[:150]}")
    if s not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — create: {s}")
        sys.exit(2)

    # fire 3 async batches (wait=false) and delete while they are in flight
    statuses = []
    for b in range(3):
        pts = [{"id": i, "vector": [0.1 * i, 0.2, 0.3, 0.4 + 0.01 * b]}
               for i in OLD_IDS[3 * b:3 * b + 3]]
        sb, _, rawb = safe_request("PUT", f"/collections/{E}/points?wait=false",
                                   {"points": pts})
        statuses.append(sb)
        print(f"async batch {b}: {sb} {rawb[:100]}")
    s_del, _, raw_del = safe_request("DELETE", f"/collections/{E}")
    print(f"delete racing async writes: {s_del} {raw_del[:150]}")
    if s_del == 0 or 500 <= s_del <= 599:
        print("VERDICT: SCRIPT_ERROR — transport/server error on delete")
        sys.exit(2)
    if s_del != 200:
        print(f"note: racing delete returned {s_del}; continuing to recreate probe")

    # collection must be gone (poll briefly for async teardown)
    gone = False
    for _ in range(10):
        s, _, raw = safe_request("GET", f"/collections/{E}")
        if s == 404:
            gone = True
            break
        if s == 200:
            time.sleep(0.5)
            continue
        print(f"note: describe returned {s} during teardown poll")
        break
    print(f"gone after delete: {gone}")
    if not gone:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print("collection still readable 5s after successful DELETE with "
              "async writes in flight")
        sys.exit(1)

    # recreate same name; give any in-flight/replay work time to land
    s, _, raw = safe_request("PUT", f"/collections/{E}",
                             {"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"recreate: {s} {raw[:150]}")
    if s not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — recreate: {s}")
        sys.exit(2)
    time.sleep(2.0)

    s, body, raw = safe_request("POST", f"/collections/{E}/points/count",
                                {"exact": True})
    n = body.get("result", {}).get("count") if isinstance(body, dict) else None
    print(f"count after recreate+2s: {s} count={n}")
    if s == 200 and n not in (0, None):
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"{n} points from pre-delete async writes resurrected into the "
              "recreated collection (state replay across delete boundary)")
        sys.exit(1)

    s, body, raw = safe_request("POST", f"/collections/{E}/points/scroll",
                                {"limit": 100, "with_payload": True})
    points = (body.get("result", {}) or {}).get("points", []) \
        if isinstance(body, dict) else []
    print(f"scroll after recreate: {s} n={len(points)} ids="
          f"{sorted(p.get('id') for p in points)}")
    if s == 200 and points:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"recreated collection contains {len(points)} resurrected points")
        sys.exit(1)

    for pid in (1, 5, 9):
        s, _, raw = safe_request("GET", f"/collections/{E}/points/{pid}")
        print(f"get old point {pid}: {s}")
        if s == 200:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"pre-delete point {pid} resurrected and readable after recreate")
            sys.exit(1)
    print(f"async batch statuses (not judged): {statuses}")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)
finally:
    cleanup(E)
