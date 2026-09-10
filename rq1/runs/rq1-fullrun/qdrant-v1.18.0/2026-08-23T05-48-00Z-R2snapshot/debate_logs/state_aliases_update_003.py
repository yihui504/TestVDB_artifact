# script_id: state_aliases_update_003
# strategy: delete_consistency
# endpoint: aliases+update
# Attack: qdrant_state_aliases_update_001 (原子性 × 目标 collection 删除时的 alias 状态残留)
# constraint_ids: qdrant_state_aliases_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
# doc_version: 1.18.x (versioned)
# Blindspot: BS-03 Concurrency State Blindness (dangling alias state)
"""
State: create collection a + alias x -> a; DELETE collection a directly
(without removing the alias). Then inspect alias state:
  GET /collections/aliases must not contain a dangling x -> a entry, OR
  querying via alias x must return a clean 404, never 500/panic.
Also: alias recreate onto a NEW collection c via atomic batch must succeed
(no corrupted alias state left behind by the dangling reference).
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
COLL_A = f"st_dang_a_{TS}"
COLL_C = f"st_dang_c_{TS}"
ALIAS  = f"st_dang_x_{TS}"
CREATE_PATH = "/collections/{name}"
ALIAS_UPDATE = "/collections/aliases"
LIST_ALIASES = "/collections/aliases"
COUNT_PATH = "/collections/{name}/points/count"
DIM = 4

def cleanup():
    for name in (COLL_A, COLL_C):
        try:
            safe_request("DELETE", CREATE_PATH.format(name=name))
        except Exception:
            pass
    try:
        safe_request("POST", ALIAS_UPDATE, json={
            "actions": [{"delete_alias": {"alias_name": ALIAS}}]})
    except Exception:
        pass

try:
    st, _, raw = safe_request("PUT", CREATE_PATH.format(name=COLL_A),
                              json={"vectors": {"size": DIM, "distance": "Cosine"}})
    print(f"create a: {st} {raw[:150]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)
    st, _, raw = safe_request("POST", ALIAS_UPDATE, json={
        "actions": [{"create_alias": {"alias_name": ALIAS, "collection_name": COLL_A}}]})
    print(f"alias -> a: {st} {raw[:150]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)

    # delete target collection directly
    st, _, raw = safe_request("DELETE", CREATE_PATH.format(name=COLL_A))
    print(f"delete a: {st} {raw[:150]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)
    time.sleep(1)

    # query via dangling alias: 404 expected; 500/0 = defect
    st, _, raw = safe_request("POST", COUNT_PATH.format(name=ALIAS), json={"exact": True})
    print(f"count via dangling alias: {st} {raw[:200]}")
    if st == 0 or st >= 500:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — dangling alias query returned {st}: {raw[:200]}")
        sys.exit(1)

    # alias listing must be consistent (no crash / parseable)
    st, body, raw = safe_request("GET", LIST_ALIASES)
    print(f"list aliases: {st} {raw[:300]}")
    if st == 0 or st >= 500:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — alias list after target delete {st}: {raw[:200]}")
        sys.exit(1)

    # recreate: new collection c + atomic alias re-point
    st, _, raw = safe_request("PUT", CREATE_PATH.format(name=COLL_C),
                              json={"vectors": {"size": DIM, "distance": "Cosine"}})
    print(f"create c: {st} {raw[:150]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)
    st, _, raw = safe_request("POST", ALIAS_UPDATE, json={
        "actions": [
            {"delete_alias": {"alias_name": ALIAS}},
            {"create_alias": {"alias_name": ALIAS, "collection_name": COLL_C}},
        ]})
    print(f"re-point alias: {st} {raw[:200]}")
    if st not in (200, 201):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — alias re-point after dangling state rejected: {st} {raw[:200]}")
        sys.exit(1)

    st, _, raw = safe_request("POST", COUNT_PATH.format(name=ALIAS), json={"exact": True})
    print(f"count via re-pointed alias: {st} {raw[:200]}")
    if st != 200:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — re-pointed alias not queryable: {st}")
        sys.exit(1)

    print("VERDICT: NO_DEFECT")
    sys.exit(0)
except SystemExit:
    raise
except Exception as e:
    print(f"UNEXPECTED_ERROR: {e}")
    print("VERDICT: SCRIPT_ERROR")
    sys.exit(2)
finally:
    cleanup()
