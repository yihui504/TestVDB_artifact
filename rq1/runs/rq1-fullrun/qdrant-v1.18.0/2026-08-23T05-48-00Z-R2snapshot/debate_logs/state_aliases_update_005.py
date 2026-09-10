# script_id: state_aliases_update_005
# strategy: concurrent
# endpoint: aliases+update
# Attack: qdrant_state_aliases_update_001 (原子性 × 并发独立 alias 批次交错)
# constraint_ids: qdrant_state_aliases_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
# doc_version: 1.18.x (versioned)
# Blindspot: BS-03 Concurrency State Blindness
"""
State/concurrent: many threads concurrently issue SEPARATE aliases+update
batches that all converge on the same final binding (delete x + create x->b).
Atomicity invariant: after the storm, alias list must show exactly ONE
binding x->b — no duplicate rows, no lost delete, no 500s. Concurrent
conflicting deletes may legitimately 4xx; only 5xx / corrupted final state
are defects.
"""
import requests, json, sys, os, time, threading

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
COLL_A = f"st_storm_a_{TS}"
COLL_B = f"st_storm_b_{TS}"
ALIAS  = f"st_storm_x_{TS}"
CREATE_PATH = "/collections/{name}"
ALIAS_UPDATE = "/collections/aliases"
LIST_ALIASES = "/collections/aliases"
DIM = 4
N_THREADS = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "20"))

def cleanup():
    for name in (COLL_A, COLL_B):
        try:
            safe_request("DELETE", CREATE_PATH.format(name=name))
        except Exception:
            pass
    try:
        safe_request("POST", ALIAS_UPDATE, json={
            "actions": [{"delete_alias": {"alias_name": ALIAS}}]})
    except Exception:
        pass

server_errors = []

def worker():
    for _ in range(10):
        st, _, raw = safe_request("POST", ALIAS_UPDATE, json={
            "actions": [
                {"delete_alias": {"alias_name": ALIAS}},
                {"create_alias": {"alias_name": ALIAS, "collection_name": COLL_B}},
            ]})
        if st == 0 or st >= 500:
            server_errors.append((st, raw[:200]))
        time.sleep(0.02)

try:
    ok = True
    for name in (COLL_A, COLL_B):
        st, _, raw = safe_request("PUT", CREATE_PATH.format(name=name),
                                  json={"vectors": {"size": DIM, "distance": "Cosine"}})
        print(f"create {name}: {st} {raw[:120]}")
        if st not in (200, 201):
            ok = False
            break
    if not ok:
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)

    st, _, raw = safe_request("POST", ALIAS_UPDATE, json={
        "actions": [{"create_alias": {"alias_name": ALIAS, "collection_name": COLL_A}}]})
    print(f"initial alias->a: {st} {raw[:150]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)

    threads = [threading.Thread(target=worker) for _ in range(N_THREADS)]
    for t in threads: t.start()
    for t in threads: t.join()
    time.sleep(2)

    if server_errors:
        print(f"5xx during storm ({len(server_errors)}): {server_errors[:3]}")
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — concurrent alias batches caused 5xx")
        sys.exit(1)

    st, body, raw = safe_request("GET", LIST_ALIASES)
    print(f"final aliases: {st} {raw[:400]}")
    if st == 0 or st >= 500:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — alias list {st}")
        sys.exit(1)
    result = (body or {}).get("result") if isinstance(body, dict) else None
    entries = result.get("aliases") if isinstance(result, dict) else None
    if not isinstance(entries, list):
        print("VERDICT: SCRIPT_ERROR — unparseable alias list")
        sys.exit(2)
    bound = [e.get("collection_name") for e in entries
             if isinstance(e, dict) and e.get("alias_name") == ALIAS]
    if bound != [COLL_B]:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — post-storm alias state corrupted: {bound}")
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
