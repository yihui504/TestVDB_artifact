# script_id: semantic_aliases_update_003
# strategy: type_coercion + illegal_rejection (mixed)
# endpoint: aliases+update
# Attack: qdrant_state_aliases_update_001 — actions 类型混淆/结构违规 + 合法值被错误拒绝
# constraint_ids: qdrant_state_aliases_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
# doc_version: 1.18.x (versioned)
# Blindspot: BS-01 Parameter Type Coercion Trust
"""
Type confusion on actions: string instead of array, single object instead of
array, unknown action verb, actions=[], collection_name numeric. Also verify
legal inputs (empty timeout omitted, unicode alias) are NOT wrongly rejected.
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
COLL = f"sem_alias_type_{TS}"
CREATE_PATH = "/collections/{name}"
ALIAS_UPDATE = "/collections/aliases"

def cleanup():
    try:
        safe_request("DELETE", CREATE_PATH.format(name=COLL))
    except Exception:
        pass

try:
    st, _, raw = safe_request("PUT", CREATE_PATH.format(name=COLL),
                              json={"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"setup create: {st} {raw[:200]}")
    if st not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — setup failed: {st}")
        sys.exit(2)

    # --- illegal: actions as string ---
    st, _, raw = safe_request("POST", ALIAS_UPDATE, json={"actions": "create_alias"})
    print(f"actions=string: {st} {raw[:200]}")
    if st == 200:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — string actions accepted")
        sys.exit(1)

    # --- illegal: single action object not wrapped in array ---
    st, _, raw = safe_request("POST", ALIAS_UPDATE,
        json={"actions": {"create_alias": {"alias": "x", "collection_name": COLL}}})
    print(f"actions=object: {st} {raw[:200]}")
    if st == 200:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — bare object actions accepted")
        sys.exit(1)

    # --- illegal: unknown action verb ---
    st, _, raw = safe_request("POST", ALIAS_UPDATE,
        json={"actions": [{"drop_alias": {"alias": "x", "collection_name": COLL}}]})
    print(f"unknown verb drop_alias: {st} {raw[:200]}")
    if st == 200:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — unknown action verb accepted")
        sys.exit(1)

    # --- illegal: collection_name numeric ---
    st, _, raw = safe_request("POST", ALIAS_UPDATE,
        json={"actions": [{"create_alias": {"alias": "n", "collection_name": 12345}}]})
    print(f"collection_name=12345: {st} {raw[:200]}")
    if st == 200:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — numeric collection_name accepted")
        sys.exit(1)

    # --- illegal: actions=[] empty array ---
    st, _, raw = safe_request("POST", ALIAS_UPDATE, json={"actions": []})
    print(f"actions=[]: {st} {raw[:200]}")
    if st == 200:
        # empty batch may be a documented no-op; only flag if it returns an error-shaped 200
        print("NOTE: empty actions accepted (possible no-op, judged by reviewer)")

    # --- legal: unicode alias + rename to same collection ---
    alias = f"сэм_alias_{TS}"
    st, _, raw = safe_request("POST", ALIAS_UPDATE,
        json={"actions": [{"create_alias": {"alias": alias, "collection_name": COLL}}]})
    print(f"unicode alias create: {st} {raw[:200]}")
    if st not in (200, 201):
        print("VERDICT: DEFECT_FOUND (Type1_IllegalRejection)")
        print(f"Legal unicode alias rejected: {raw[:300]}")
        sys.exit(1)

    # --- legal: rename_alias to same collection (should succeed) ---
    st, _, raw = safe_request("POST", ALIAS_UPDATE,
        json={"actions": [{"rename_alias": {"old_alias_name": alias, "new_collection_name": COLL}}]})
    print(f"rename same target: {st} {raw[:200]}")
    if st not in (200, 201):
        print("VERDICT: DEFECT_FOUND (Type1_IllegalRejection)")
        print(f"Legal rename alias to its current collection rejected: {raw[:300]}")
        sys.exit(1)

    # cleanup alias
    try:
        safe_request("POST", ALIAS_UPDATE,
            json={"actions": [{"delete_alias": {"alias": alias}}]})
    except Exception:
        pass

    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
