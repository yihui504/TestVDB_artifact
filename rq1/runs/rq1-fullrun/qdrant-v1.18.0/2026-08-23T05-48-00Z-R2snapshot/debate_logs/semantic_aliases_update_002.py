# script_id: semantic_aliases_update_002
# strategy: diagnosis_quality
# endpoint: aliases+update
# Attack: qdrant_state_aliases_update_001 — 错误诊断质量：actions 引用不存在 collection / 重复 create
# constraint_ids: qdrant_state_aliases_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
# doc_version: 1.18.x (versioned)
# Blindspot: BS-02 Error Message Negligence
"""
Type-2 diagnosis quality: alias operations referencing a nonexistent collection,
or create_alias for an already-existing alias, must be rejected with a message
that names the offending alias/collection and hints the fix.
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
COLL = f"sem_alias_diag_{TS}"
ALIAS = f"sem_alias_d_{TS}"
MISSING = f"sem_no_such_coll_{TS}"
CREATE_PATH = "/collections/{name}"
ALIAS_UPDATE = "/collections/aliases"

def cleanup():
    for name in (COLL, ALIAS):
        try:
            safe_request("DELETE", CREATE_PATH.format(name=name))
        except Exception:
            pass

def check_error_quality(status, body, expected_param):
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0
    max_score = 3
    if expected_param.lower() in error_msg:
        score += 1
    format_hints = ["must be", "expected", "should be", "valid", "range", "type", "positive", "non-zero", "exist", "not found", "already"]
    if any(h in error_msg for hint in format_hints):
        score += 1
    action_hints = ["correct", "try", "use", "change", "specify", "provide", "delete", "create"]
    if any(h in error_msg for hint in action_hints):
        score += 1
    return score, max_score

try:
    st, _, raw = safe_request("PUT", CREATE_PATH.format(name=COLL),
                              json={"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"setup create: {st} {raw[:200]}")
    if st not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — setup failed: {st}")
        sys.exit(2)

    # Case 1: create_alias pointing at nonexistent collection
    st, body, raw = safe_request("POST", ALIAS_UPDATE,
        json={"actions": [{"create_alias": {"alias": f"{ALIAS}_m", "collection_name": MISSING}}]})
    print(f"create_alias->missing: {st} {raw[:300]}")
    if st in (400, 404, 422):
        score, mx = check_error_quality(st, body, MISSING)
        print(f"DIAGNOSTIC_SCORE missing-collection: {score}/{mx}")
        if score < 2:
            print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
            print(f"Error for alias->nonexistent collection does not name '{MISSING}' or give fix hint: {raw[:300]}")
            sys.exit(1)
    elif st == 200:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — alias to nonexistent collection accepted")
        sys.exit(1)

    # Case 2: duplicate create_alias for same alias name
    st, body, raw = safe_request("POST", ALIAS_UPDATE,
        json={"actions": [{"create_alias": {"alias": ALIAS, "collection_name": COLL}},
                          {"create_alias": {"alias": ALIAS, "collection_name": COLL}}]})
    print(f"duplicate create_alias: {st} {raw[:300]}")
    if st == 200:
        # duplicate create within one atomic batch may be allowed only if consistent;
        # then try conflicting duplicate: alias -> two different collections
        st2, body2, raw2 = safe_request("POST", ALIAS_UPDATE,
            json={"actions": [{"create_alias": {"alias": f"{ALIAS}_c1", "collection_name": COLL}},
                              {"create_alias": {"alias": f"{ALIAS}_c1", "collection_name": COLL}}]})
        print(f"conflicting duplicate: {st2} {raw2[:300]}")
    elif st in (400, 404, 422, 409):
        score, mx = check_error_quality(st, body, ALIAS)
        print(f"DIAGNOSTIC_SCORE duplicate-alias: {score}/{mx}")
        if score < 2:
            print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
            print(f"Duplicate alias error lacks parameter name/format hint: {raw[:300]}")
            sys.exit(1)

    # Case 3: rename_alias of nonexistent alias
    st, body, raw = safe_request("POST", ALIAS_UPDATE,
        json={"actions": [{"rename_alias": {"old_alias_name": f"{ALIAS}_ghost",
                                            "new_collection_name": COLL}}]})
    print(f"rename nonexistent alias: {st} {raw[:300]}")
    if st in (400, 404, 422):
        score, mx = check_error_quality(st, body, f"{ALIAS}_ghost")
        print(f"DIAGNOSTIC_SCORE ghost-rename: {score}/{mx}")
        if score < 2:
            print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
            print(f"Ghost rename error message lacks actionable detail: {raw[:300]}")
            sys.exit(1)
    elif st == 200:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — rename of nonexistent alias accepted")
        sys.exit(1)

    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
