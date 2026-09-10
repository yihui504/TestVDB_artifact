# script_id: semantic_aliases_collection_list_004
# strategy: illegal_rejection
# endpoint: aliases+collection+list
# constraint_ids: qdrant_behavioral_aliases_collection_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collection-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (parameter disposition trust - URL path handling of legal name characters)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: illegal_rejection x qdrant_behavioral_aliases_collection_list_001 (reverse of the 404 branch: every collection name the server accepted at create time over the legal charset family must list aliases with HTTP 200 - asymmetric 404/500 on an existing collection = wrongful rejection)
Oracle: for each collection name in the legal charset family (letters/digits/underscore/dot/dash, incl. mixed case) that PUT create accepted with 2xx, GET /collections/{name}/aliases returns HTTP 200; any 404/5xx on such an existing name is Type1_IllegalRejection/Type3

Reverse (positive-side) consistency check of assertion
qdrant_behavioral_aliases_collection_list_001: an EXISTING collection must
answer HTTP 200 when its aliases are listed.

Server acceptance at create time is ground truth for 'existing collection':
  - create the collection over the legal name charset family (letters, digits,
    underscores, dots, dashes, mixed case, leading underscore);
  - if create answers 2xx the name is an existing collection, so the alias
    listing MUST answer 200. A 404/500 asymmetry on such a name would mean the
    listing layer mishandles legal names (e.g. path parsing of '.', '-', case)
    that the create layer accepts - a wrongful rejection (Type1_IllegalRejection)
    or runtime failure (Type3) of legal input.
  - if create itself refuses (4xx), the name is not an existing collection and
    the listing promise does not apply to it -> variant skipped, not a defect
    (avoids doc-as-ground on the exact charset: the server is the authority).

Path templates are derived from the contract api_endpoints:
  aliases+collection+list -> GET /collections/{collection_name}/aliases
  collections+create      -> PUT /collections/{collection_name}
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

# legal charset family: leading letter/underscore, then alnum plus . - _
NAME_FAMILY = [
    f"s4.aclist-dotdash.{TS}",       # dots + dash
    f"_s4_aclist_under_{TS}",        # leading underscore
    f"s4AclistCase{TS}",             # mixed case
    f"s4.aclist.9digits.{TS}",       # digits after dots
]

COLL_REL = "/collections/{name}"
LIST_ALIASES_REL = "/collections/{name}/aliases"


def cleanup():
    for name in NAME_FAMILY:
        try:
            safe_request("DELETE", COLL_REL.format(name=name), timeout=15)
        except Exception:
            pass


try:
    created = []
    for name in NAME_FAMILY:
        st, _, raw = safe_request("PUT", COLL_REL.format(name=name),
                                  json={"vectors": {"size": 4, "distance": "Cosine"}})
        print(f"create '{name}': {st} {raw[:200]}")
        if st == -1:
            alive = liveness_ok()
            print(f"VERDICT: SCRIPT_ERROR - transport failure creating '{name}' (server alive={alive})")
            sys.exit(2)
        if 200 <= st < 300:
            created.append(name)
        elif st >= 500:
            print(f"VERDICT: SCRIPT_ERROR - create of legal-name variant '{name}' failed with server error {st}: {raw[:300]}")
            sys.exit(2)
        else:
            print(f"note: server refused to create '{name}' ({st}); listing promise does not apply, variant skipped")

    if not created:
        print("VERDICT: SCRIPT_ERROR - no legal-name variant was accepted at create time; nothing to test")
        sys.exit(2)

    for name in created:
        st, _, raw = safe_request("GET", LIST_ALIASES_REL.format(name=name))
        print(f"list aliases of existing '{name}': {st} {raw[:300]}")
        if st == -1:
            alive = liveness_ok()
            print(f"VERDICT: SCRIPT_ERROR - transport failure listing '{name}' (server alive={alive})")
            sys.exit(2)
        if st == 404:
            print("VERDICT: DEFECT_FOUND (Type1_IllegalRejection)")
            print(f"collection '{name}' was accepted by create (2xx) yet alias listing answers 404 - legal existing input wrongly rejected")
            sys.exit(1)
        if st >= 500:
            print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure)")
            print(f"collection '{name}' was accepted by create (2xx) yet alias listing crashes with {st}")
            sys.exit(1)
        if st != 200:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"collection '{name}' was accepted by create (2xx) yet alias listing answered {st}, expected 200")
            sys.exit(1)

    print(f"all {len(created)} existing legal-name variants listed aliases with HTTP 200")
    print("VERDICT: NO_DEFECT")
finally:
    cleanup()

