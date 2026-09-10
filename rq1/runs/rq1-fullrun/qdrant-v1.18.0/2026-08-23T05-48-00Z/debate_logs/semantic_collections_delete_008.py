# script_id: semantic_collections_delete_008
# strategy: illegal_rejection
# endpoint: collections+delete
# Attack: qdrant_state_collections_delete_001 happy-path with legal timeout query values
#         (timeout: integer, min 1, optional) — DELETE /collections/{name}?timeout=1|10|60
#         must stay 200; a 4xx on a legal value is Type1_IllegalRejection
# constraint_ids: qdrant_state_collections_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-04 boundary values on optional query params (legal-acceptance slice)
# Block: chunk_collections+delete
"""Type-1 reverse: the contract declares timeout as an optional integer query
param (min 1) on collections+delete. Legal values 1 (min), 10 and 60 must all
be accepted with 200 on an existing collection. Rejecting any of them is an
illegal rejection of a documented-legal input."""
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


def recreate(name):
    s, _, raw = safe_request("PUT", f"/collections/{name}",
                             {"vectors": {"size": 4, "distance": "Cosine"}})
    if s not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — create: {s} {raw[:150]}")
        sys.exit(2)


T = f"sem_del_to_{TS}"
try:
    for tv in (1, 10, 60):
        recreate(T)
        s, _, raw = safe_request("DELETE", f"/collections/{T}?timeout={tv}")
        print(f"DELETE ?timeout={tv}: {s} {raw[:200]}")
        if s == 0 or 500 <= s <= 599:
            print(f"VERDICT: SCRIPT_ERROR — transport/server error ({s})")
            sys.exit(2)
        if s != 200:
            print("VERDICT: DEFECT_FOUND (Type1_IllegalRejection)")
            print(f"legal timeout={tv} (integer >= 1 per contract) wrongly "
                  f"rejected with status {s}")
            sys.exit(1)
        # verify the delete actually took effect (200 must mean deleted)
        s2, _, raw2 = safe_request("GET", f"/collections/{T}")
        if s2 == 200:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"DELETE ?timeout={tv} returned 200 but collection persists")
            sys.exit(1)
    print("VERDICT: NO_DEFECT")
    sys.exit(0)
finally:
    cleanup(T)
