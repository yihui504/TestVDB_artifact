# script_id: semantic_aliases_collection_list_002
# strategy: behavioral_contract
# endpoint: aliases+collection+list
# constraint_ids: qdrant_behavioral_aliases_collection_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collection-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (semantic-contract verification of the 404 branch)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: behavioral_contract x qdrant_behavioral_aliases_collection_list_001 (negative branch: unknown / already-deleted collection must yield HTTP 404, not a silent 200 empty list)
Oracle: GET /collections/{name}/aliases returns HTTP 404 for a collection name that does not exist (never-created or deleted); any 200/2xx empty-list success violates the assertion's 404 promise and is Type1_IllegalSuccess

Contract assertion qdrant_behavioral_aliases_collection_list_001 negative branch:
  "unknown collection: HTTP 404".

A listing endpoint that answers 200-with-empty-list for a name that never existed
would silently mask typos/races (the caller cannot distinguish 'no aliases yet'
from 'wrong collection name'), so the assertion's 404 promise is behaviorally
load-bearing. Two state variants are exercised:
  (a) a never-created collection name;
  (b) a collection that existed and was deleted (state-transition variant of the
      same promise - after deletion the name must not keep answering 200).

Path templates are derived from the contract api_endpoints:
  aliases+collection+list -> GET /collections/{collection_name}/aliases
  collections+create      -> PUT /collections/{collection_name}
  collections+get         -> GET /collections/{collection_name}
"""
import os
import sys
import json
import time
import requests

# --- X1 bootstrap three-layer fallback: env -> upward walk -> contract target ---
BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)


def resolve_contract_target():
    t = os.environ.get("TESTVDB_TARGET")
    if t:
        return t
    start = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.dirname(os.path.abspath(__file__))
    cur = os.path.abspath(start)
    while True:
        cand = os.path.join(cur, "structured_contract.json")
        if os.path.exists(cand):
            try:
                with open(cand, encoding="utf-8") as fh:
                    return json.load(fh).get("target")
            except Exception:
                return None
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


TARGET = resolve_contract_target()
if TARGET is not None and TARGET != "qdrant":
    print(f"VERDICT: SCRIPT_ERROR - contract target mismatch (expected qdrant, got {TARGET})")
    sys.exit(2)


def safe_request(method, endpoint, json=None, timeout=20):
    """Authoritative wrapper from agents/_target_api_reference.md; returns (status, body, raw)."""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        resp = requests.request(method=method, url=url, json=json, headers=headers, timeout=timeout)
        raw_text = resp.text
        try:
            body = resp.json()
        except Exception:
            body = raw_text
        return resp.status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)


def liveness_ok():
    for ep in ("/readyz", "/livez", "/"):
        try:
            st, _, _ = safe_request("GET", ep, timeout=5)
            if st == 200:
                return True
        except Exception:
            continue
    return False


TS = str(int(time.time()))
GHOST = f"s2_aclist_ghost_{TS}"
DELETED = f"s2_aclist_del_{TS}"

COLL_REL = "/collections/{name}"
COLL_GET_REL = "/collections/{name}"
LIST_ALIASES_REL = "/collections/{name}/aliases"


def cleanup():
    try:
        safe_request("DELETE", COLL_REL.format(name=GHOST), timeout=15)
    except Exception:
        pass
    try:
        safe_request("DELETE", COLL_REL.format(name=DELETED), timeout=15)
    except Exception:
        pass


def expect_404(collection_name, context):
    """Shared oracle: this listing of a non-existent collection must be HTTP 404.
    Returns True when the promise holds, otherwise prints a verdict and exits."""
    st, _, raw = safe_request("GET", LIST_ALIASES_REL.format(name=collection_name))
    print(f"list aliases of {context} collection '{collection_name}': {st} {raw[:400]}")
    if st == -1:
        alive = liveness_ok()
        print(f"VERDICT: SCRIPT_ERROR - transport failure (server alive={alive}), no defect conclusion")
        sys.exit(2)
    if st == 404:
        return True
    if 200 <= st < 300:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
        print(f"assertion promises HTTP 404 for unknown collection '{collection_name}'; got {st} with a silent success payload instead")
        sys.exit(1)
    if st >= 500:
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure)")
        print(f"unknown collection '{collection_name}' should be rejected with 404; got server error {st}")
        sys.exit(1)
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
    print(f"unknown collection '{collection_name}' should be rejected with 404; got unexpected status {st}")
    sys.exit(1)


try:
    # ---- guard: make sure the ghost name really is free before probing ----
    try:
        st, _, raw = safe_request("DELETE", COLL_REL.format(name=GHOST), timeout=15)
        print(f"guard delete ghost {GHOST}: {st} {raw[:160]}")
    except Exception:
        pass

    # ---- (a) never-created collection name must 404 ----
    expect_404(GHOST, "never-created")

    # ---- (b) deleted collection: create it, delete it, wait for deletion, then list ----
    st, _, raw = safe_request("PUT", COLL_REL.format(name=DELETED),
                              json={"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"setup create {DELETED}: {st} {raw[:160]}")
    if st == -1:
        alive = liveness_ok()
        print(f"VERDICT: SCRIPT_ERROR - transport failure creating {DELETED} (server alive={alive})")
        sys.exit(2)
    if st not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR - setup failed creating {DELETED}: {st} {raw[:300]}")
        sys.exit(2)

    st, _, raw = safe_request("DELETE", COLL_REL.format(name=DELETED), timeout=15)
    print(f"delete {DELETED}: {st} {raw[:160]}")
    if st == -1:
        alive = liveness_ok()
        print(f"VERDICT: SCRIPT_ERROR - transport failure deleting {DELETED} (server alive={alive})")
        sys.exit(2)
    if st != 200:
        print(f"VERDICT: SCRIPT_ERROR - setup delete failed for {DELETED}: {st} {raw[:300]}")
        sys.exit(2)

    gone = False
    for _ in range(50):
        st, _, _ = safe_request("GET", COLL_GET_REL.format(name=DELETED), timeout=10)
        if st == 404:
            gone = True
            break
        time.sleep(0.2)
    if not gone:
        print(f"VERDICT: SCRIPT_ERROR - collection {DELETED} still exists after delete (status {st}), cannot test the deleted-name promise")
        sys.exit(2)

    expect_404(DELETED, "deleted")

    print("VERDICT: NO_DEFECT")
finally:
    cleanup()

