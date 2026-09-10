# script_id: semantic_aliases_collection_list_001
# strategy: behavioral_contract
# endpoint: aliases+collection+list
# constraint_ids: qdrant_behavioral_aliases_collection_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collection-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (semantic-contract verification / doc drift on listing semantics)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: behavioral_contract x qdrant_behavioral_aliases_collection_list_001 (positive: 200 with full own-alias list {alias_name, collection_name}, per-collection scoping, empty-list boundary closure)
Oracle: existing collections return HTTP 200 and the result lists exactly their own aliases (col_main -> {alias_a, alias_b} each with alias_name+collection_name fields, col_other -> {alias_c}, alias-free collection -> empty array) with no foreign-alias leak

Contract assertion qdrant_behavioral_aliases_collection_list_001:
  "returns 200 with a list of {alias, collection_name}; 404 for an unknown collection"
(endpoint description: "List the aliases of one collection").

Positive-branch verification of the promise:
  (1) every existing collection returns HTTP 200;
  (2) the result is a list of the collection's OWN aliases, each item shaped as
      {alias_name, collection_name} (fields per the contract's alias list shape);
  (3) aliases registered on OTHER collections do not leak into this listing;
  (4) an existing collection without any alias still returns 200 with an empty
      list (boundary closure - the promise is "200 with its aliases", empty is
      the minimal legal instance of "its aliases").

Path templates below are derived from the contract api_endpoints paths:
  aliases+collection+list  -> GET  /collections/{collection_name}/aliases
  collections+create       -> PUT  /collections/{collection_name}
  aliases+update           -> POST /collections/aliases
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
    """Layer 1: TESTVDB_TARGET env. Layer 2: TESTVDB_SCRIPTS_DIR or script dir,
    upward-walk to the directory holding structured_contract.json. Layer 3: read
    its 'target' field. Returns None only when all layers fail."""
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
    """Lightweight health re-check used only on transport failures (G8/D3b)."""
    for ep in ("/readyz", "/livez", "/"):
        try:
            st, _, _ = safe_request("GET", ep, timeout=5)
            if st == 200:
                return True
        except Exception:
            continue
    return False


def transport_script_error(context):
    """Shared transport-failure handling: re-check liveness, then SCRIPT_ERROR
    (G8: transport failures never produce defect conclusions)."""
    alive = liveness_ok()
    print(f"VERDICT: SCRIPT_ERROR - transport failure {context} (server alive={alive}), no defect conclusion")
    sys.exit(2)


def extract_alias_list(body):
    """Qdrant alias responses: 'result' is either the alias array
    (per-collection list) or an object {'aliases': [...]} (global list).
    Return the list, or None when the body does not carry one."""
    if not isinstance(body, dict):
        return None
    res = body.get("result")
    if isinstance(res, list):
        return res
    if isinstance(res, dict) and isinstance(res.get("aliases"), list):
        return res.get("aliases")
    return None


TS = str(int(time.time()))
COL_MAIN = f"s1_aclist_main_{TS}"
COL_OTHER = f"s1_aclist_other_{TS}"
COL_EMPTY = f"s1_aclist_empty_{TS}"
ALIAS_A = f"s1_al_a_{TS}"
ALIAS_B = f"s1_al_b_{TS}"
ALIAS_C = f"s1_al_c_{TS}"

COLL_REL = "/collections/{name}"
LIST_ALIASES_REL = "/collections/{name}/aliases"
ALIAS_UPDATE_REL = "/collections/aliases"


def cleanup():
    """Teardown: aliases first (a collection guarded by an alias refuses deletion),
    then collections. Cleanup failure must never fail the script."""
    for al in (ALIAS_A, ALIAS_B, ALIAS_C):
        try:
            safe_request("POST", ALIAS_UPDATE_REL,
                         json={"actions": [{"delete_alias": {"alias_name": al}}]}, timeout=15)
        except Exception:
            pass
    for name in (COL_MAIN, COL_OTHER, COL_EMPTY):
        try:
            safe_request("DELETE", COLL_REL.format(name=name), timeout=15)
        except Exception:
            pass


def create_collection(name):
    """PUT /collections/{name} with a minimal vector config (contract data_types:
    vectors map of {size, distance})."""
    return safe_request("PUT", COLL_REL.format(name=name),
                        json={"vectors": {"size": 4, "distance": "Cosine"}})


try:
    # ---- setup: three collections; alias_a+alias_b on COL_MAIN, alias_c on COL_OTHER ----
    for name in (COL_MAIN, COL_OTHER, COL_EMPTY):
        st, _, raw = create_collection(name)
        print(f"setup create {name}: {st} {raw[:160]}")
        if st == -1:
            transport_script_error(f"creating {name}")
        if st not in (200, 201):
            print(f"VERDICT: SCRIPT_ERROR - setup failed creating {name}: {st} {raw[:300]}")
            sys.exit(2)

    st, _, raw = safe_request("POST", ALIAS_UPDATE_REL, json={"actions": [
        {"create_alias": {"collection_name": COL_MAIN, "alias_name": ALIAS_A}},
        {"create_alias": {"collection_name": COL_MAIN, "alias_name": ALIAS_B}},
    ]})
    print(f"setup create_alias batch on {COL_MAIN}: {st} {raw[:200]}")
    if st == -1:
        transport_script_error("creating alias batch")
    if st != 200:
        print(f"VERDICT: SCRIPT_ERROR - setup create_alias failed: {st} {raw[:300]}")
        sys.exit(2)

    st, _, raw = safe_request("POST", ALIAS_UPDATE_REL, json={"actions": [
        {"create_alias": {"collection_name": COL_OTHER, "alias_name": ALIAS_C}},
    ]})
    print(f"setup create_alias on {COL_OTHER}: {st} {raw[:200]}")
    if st == -1:
        transport_script_error("creating alias on COL_OTHER")
    if st != 200:
        print(f"VERDICT: SCRIPT_ERROR - setup create_alias failed: {st} {raw[:300]}")
        sys.exit(2)

    # ---- (1)+(2)+(3): list aliases of COL_MAIN: 200, own two aliases, right shape ----
    st, body, raw = safe_request("GET", LIST_ALIASES_REL.format(name=COL_MAIN))
    print(f"list aliases of {COL_MAIN}: {st} {raw[:500]}")
    if st == -1:
        transport_script_error(f"listing {COL_MAIN}")
    if st != 200:
        kind = "Type1_IllegalRejection" if st == 404 else ("Type3_RuntimeFailure" if st >= 500 else "Type4_StateLogicViolation")
        print(f"VERDICT: DEFECT_FOUND ({kind})")
        print(f"expected HTTP 200 for existing collection {COL_MAIN} (assertion positive branch), got status={st}")
        sys.exit(1)

    aliases = extract_alias_list(body)
    if aliases is None:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"expected a result list of {{alias_name, collection_name}} for {COL_MAIN}, response carries none: {raw[:400]}")
        sys.exit(1)
    got_names = [it.get("alias_name") for it in aliases if isinstance(it, dict)]
    expected_names = {ALIAS_A, ALIAS_B}
    print(f"list aliases of {COL_MAIN} -> names={got_names}")
    if set(got_names) != expected_names:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"expected exactly aliases {sorted(expected_names)} for {COL_MAIN}, got {got_names} (missing aliases or foreign-alias leak)")
        sys.exit(1)
    for it in aliases:
        if not isinstance(it, dict) or not isinstance(it.get("alias_name"), str) or not isinstance(it.get("collection_name"), str):
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"alias entry is not {{alias_name: str, collection_name: str}}: {it}")
            sys.exit(1)
        if it.get("collection_name") != COL_MAIN:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"alias {it.get('alias_name')} reports owner collection {it.get('collection_name')}, expected {COL_MAIN}")
            sys.exit(1)

    # ---- (3) other direction: COL_OTHER lists exactly alias_c, no leak of alias_a/b ----
    st, body, raw = safe_request("GET", LIST_ALIASES_REL.format(name=COL_OTHER))
    print(f"list aliases of {COL_OTHER}: {st} {raw[:400]}")
    if st == -1:
        transport_script_error(f"listing {COL_OTHER}")
    if st != 200:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"expected HTTP 200 for existing collection {COL_OTHER}, got status={st}")
        sys.exit(1)
    other_names = [it.get("alias_name") for it in (extract_alias_list(body) or []) if isinstance(it, dict)]
    print(f"list aliases of {COL_OTHER} -> names={other_names}")
    if other_names != [ALIAS_C]:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"expected only [{ALIAS_C}] for {COL_OTHER}, got {other_names} (cross-collection leak or missing alias)")
        sys.exit(1)

    # ---- (4) boundary closure: existing collection without aliases -> 200 with empty list ----
    st, body, raw = safe_request("GET", LIST_ALIASES_REL.format(name=COL_EMPTY))
    print(f"list aliases of alias-free {COL_EMPTY}: {st} {raw[:400]}")
    if st == -1:
        transport_script_error(f"listing {COL_EMPTY}")
    if st != 200:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"expected HTTP 200 (empty alias list) for existing collection {COL_EMPTY}, got status={st}")
        sys.exit(1)
    empty_list = extract_alias_list(body)
    if not isinstance(empty_list, list) or len(empty_list) != 0:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"expected an empty array as the minimal legal 'its aliases' instance for {COL_EMPTY}, got: {raw[:400]}")
        sys.exit(1)

    print("VERDICT: NO_DEFECT")
finally:
    cleanup()

