# script_id: semantic_aliases_update_001
# strategy: behavioral_contract
# endpoint: aliases+update
# Attack: qdrant_bc_alias_atomic_switch_001 (behavioral_contract, 原子切换语义)
# constraint_ids: qdrant_bc_alias_atomic_switch_001, qdrant_state_aliases_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
# doc_version: 1.18.x (versioned)
# Blindspot: BS-05 semantic contract
"""
Verify alias atomic switch: create collections a and b; create alias x -> a;
rename alias x -> b. Per contract, after rename, queries via x must hit b
and alias x must never be missing/ambiguous.
"""
import requests, json, sys, os, time

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)
AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")

def safe_request(method, path, **kwargs):
    url = f"{BASE_URL}{path}"
    headers = kwargs.pop("headers", {"Content-Type": "application/json"})
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER
    try:
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        status = resp.status_code
        text = resp.text
        try:
            body = resp.json() if text else {}
        except (json.JSONDecodeError, ValueError):
            print(f"JSON_DECODE_ERROR: {text[:200]}")
            return status, None, text
        return status, body, text
    except requests.exceptions.RequestException as e:
        print(f"REQUEST_ERROR: {e}")
        return 0, None, ""

TS = str(int(time.time()))
COLL_A = f"sem_alias_atomic_a_{TS}"
COLL_B = f"sem_alias_atomic_b_{TS}"
ALIAS  = f"sem_alias_x_{TS}"
CREATE_PATH = "/collections/{name}"
ALIAS_UPDATE = "/collections/aliases"
UPSERT_PATH = "/collections/{name}/points?wait=true"
LIST_PATH = "/collections/{name}"

def cleanup():
    for name in (COLL_A, COLL_B, ALIAS):
        try:
            safe_request("DELETE", CREATE_PATH.format(name=name))
        except Exception:
            pass

try:
    # setup: create two collections with distinct dims
    for name in (COLL_A, COLL_B):
        st, _, raw = safe_request("PUT", CREATE_PATH.format(name=name),
                                  json={"vectors": {"size": 4, "distance": "Cosine"}})
        print(f"setup create {name}: {st} {raw[:200]}")
        if st not in (200, 201):
            print(f"VERDICT: SCRIPT_ERROR — setup failed creating {name}: {st}")
            sys.exit(2)

    # insert marker point in A only (id 1)
    st, _, raw = safe_request("PUT", UPSERT_PATH.format(name=COLL_A),
                              json={"points": [{"id": 1, "vector": [0.1, 0.1, 0.1, 0.1],
                                                "payload": {"src": "A"}}]})
    print(f"insert A: {st} {raw[:200]}")

    # create alias x -> A
    st, _, raw = safe_request("POST", ALIAS_UPDATE,
                              json={"actions": [{"create_alias": {"alias": ALIAS, "collection_name": COLL_A}}]})
    print(f"create_alias: {st} {raw[:200]}")
    if st != 200:
        print(f"VERDICT: SCRIPT_ERROR — create_alias failed: {st}")
        sys.exit(2)

    # rename alias x -> B atomically
    st, _, raw = safe_request("POST", ALIAS_UPDATE,
                              json={"actions": [{"rename_alias": {"old_alias_name": ALIAS,
                                                                  "new_collection_name": COLL_B}}]})
    print(f"rename_alias: {st} {raw[:200]}")
    if st != 200:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"Atomic rename alias to different collection rejected: {raw[:300]}")
        sys.exit(1)

    # after rename: alias must resolve (200), pointing to B (no points)
    st, body, raw = safe_request("GET", LIST_PATH.format(name=ALIAS))
    print(f"describe via alias: {st} {raw[:300]}")
    if st != 200:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"After atomic rename, alias should resolve to collection B; got status={st}")
        sys.exit(1)

    # query via alias (scroll to read points; B should be empty since point went to A)
    st, body, raw = safe_request("POST", f"/collections/{ALIAS}/points/scroll",
                                 json={"limit": 10, "with_payload": True})
    print(f"scroll via alias: {st} {raw[:300]}")
    points = (body or {}).get("result", {}).get("points") if isinstance(body, dict) else None
    if points is None and isinstance(body, dict):
        points = body.get("result", {}).get("points")
    if st == 200 and points:
        ids = [p.get("id") for p in points]
        if 1 in ids:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Alias still routes to old collection A after atomic rename; saw point id 1: {ids}")
            sys.exit(1)

    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
