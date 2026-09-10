# script_id: state_aliases_update_002
# strategy: concurrent
# endpoint: aliases+update
# Attack: qdrant_state_aliases_update_001 (原子性约束 × 并发 alias 操作)
# constraint_ids: qdrant_state_aliases_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
# doc_version: 1.18.x (versioned)
# Blindspot: BS-03 Concurrency State Blindness
"""
State/concurrent: while N threads issue queries via alias x (-> collection a),
concurrently apply atomic alias switch x -> b (delete_alias + create_alias in
one actions batch, repeated). Invariant: alias operations are atomic —
queries via x must ALWAYS route to a full collection (a or b), never 404/
500/ambiguous partial state. Any 500 or 404-on-existing-alias during the
switch window is a state violation.
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
COLL_A = f"st_cc_a_{TS}"
COLL_B = f"st_cc_b_{TS}"
ALIAS  = f"st_cc_x_{TS}"
CREATE_PATH = "/collections/{name}"
ALIAS_UPDATE = "/collections/aliases"
UPSERT_PATH = "/collections/{name}/points?wait=true"
QUERY_PATH = "/collections/{name}/points/count"
DIM = 4
N_THREADS = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "20"))

def cleanup():
    for name in (COLL_A, COLL_B):
        try:
            safe_request("DELETE", CREATE_PATH.format(name=name))
        except Exception:
            pass

violations = []  # (status, raw)
stop = threading.Event()

def switch_thread():
    """Atomic alias switch loop: x -> a, then x -> b, alternating."""
    target = COLL_A
    while not stop.is_set():
        st, _, raw = safe_request("POST", ALIAS_UPDATE, json={
            "actions": [
                {"delete_alias": {"alias_name": ALIAS}},
                {"create_alias": {"alias_name": ALIAS, "collection_name": target}},
            ]})
        if st not in (200, 201):
            # note: delete of nonexistent alias mid-race may 404/422 — only log
            print(f"switch resp {st}: {raw[:150]}")
        target = COLL_B if target == COLL_A else COLL_A
        time.sleep(0.05)

def query_thread(tid):
    while not stop.is_set():
        st, body, raw = safe_request("POST", QUERY_PATH.format(name=ALIAS),
                                     json={"exact": True})
        if st == 0 or st >= 500:
            violations.append((st, raw[:200]))
        elif st == 404:
            # alias must exist at all times per atomicity contract
            violations.append((st, raw[:200]))
        elif st == 200 and isinstance(body, dict):
            cnt = (body.get("result") or {}).get("count")
            if cnt not in (4, 2):
                violations.append((st, f"ambiguous count {cnt}: {raw[:150]}"))
        time.sleep(0.02)

try:
    ok = True
    for name, n in ((COLL_A, 4), (COLL_B, 2)):
        st, _, raw = safe_request("PUT", CREATE_PATH.format(name=name),
                                  json={"vectors": {"size": DIM, "distance": "Cosine"}})
        print(f"create {name}: {st} {raw[:150]}")
        if st not in (200, 201):
            ok = False
            break
        pts = [{"id": i, "vector": [0.1 * (i + 1)] * DIM} for i in range(n)]
        st, _, raw = safe_request("PUT", UPSERT_PATH.format(name=name), json={"points": pts})
        if st not in (200, 201):
            ok = False
            break
    if not ok:
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)

    st, _, raw = safe_request("POST", ALIAS_UPDATE, json={
        "actions": [{"create_alias": {"alias_name": ALIAS, "collection_name": COLL_A}}]})
    print(f"initial alias: {st} {raw[:150]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)

    sw = threading.Thread(target=switch_thread)
    qts = [threading.Thread(target=query_thread, args=(i,)) for i in range(N_THREADS)]
    sw.start()
    for t in qts: t.start()
    time.sleep(15)
    stop.set()
    sw.join(); [t.join() for t in qts]

    if violations:
        print(f"violations ({len(violations)}), samples: {violations[:5]}")
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — alias atomicity broken under concurrent access")
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
