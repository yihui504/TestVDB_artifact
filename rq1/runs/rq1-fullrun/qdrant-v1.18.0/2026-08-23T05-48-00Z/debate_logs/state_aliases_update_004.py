# script_id: state_aliases_update_004
# strategy: upsert_idempotence
# endpoint: aliases+update
# Attack: qdrant_state_aliases_update_001 (原子性 × 多动作批次的中间状态)
# constraint_ids: qdrant_state_aliases_update_001, qdrant_bc_alias_atomic_switch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
# doc_version: 1.18.x (versioned)
# Blindspot: BS-03 Concurrency State Blindness (partial application)
"""
State: single actions batch containing MANY alias operations that are
internally conflicting/overlapping (create x->a, create x->b in one batch;
create-delete-create chains). Invariant "applied atomically": after the
batch returns 200, alias list must reflect a CONSISTENT final state —
exactly one binding for x matching the last action, no duplicates, and no
intermediate bindings persisted. A 200 with duplicate/contradictory x
bindings = partial application = atomicity violation.
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
COLL_A = f"st_batch_a_{TS}"
COLL_B = f"st_batch_b_{TS}"
ALIAS  = f"st_batch_x_{TS}"
CREATE_PATH = "/collections/{name}"
ALIAS_UPDATE = "/collections/aliases"
LIST_ALIASES = "/collections/aliases"
COUNT_PATH = "/collections/{name}/points/count"
DIM = 4

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

def alias_targets(body):
    """Return list of collection names bound to ALIAS from GET aliases body."""
    if not isinstance(body, dict):
        return None
    result = body.get("result")
    if not isinstance(result, dict):
        return None
    entries = result.get("aliases")
    if not isinstance(entries, list):
        return None
    names = []
    for e in entries:
        if isinstance(e, dict) and e.get("alias_name") == ALIAS:
            names.append(e.get("collection_name"))
    return names

try:
    ok = True
    for name, n in ((COLL_A, 3), (COLL_B, 7)):
        st, _, raw = safe_request("PUT", CREATE_PATH.format(name=name),
                                  json={"vectors": {"size": DIM, "distance": "Cosine"}})
        print(f"create {name}: {st} {raw[:120]}")
        if st not in (200, 201):
            ok = False
            break
        pts = [{"id": i, "vector": [0.05 * (i + 1)] * DIM} for i in range(n)]
        st, _, raw = safe_request("PUT",
            f"/collections/{name}/points?wait=true", json={"points": pts})
        if st not in (200, 201):
            ok = False
            break
    if not ok:
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)

    # 单批次内冲突动作链：create x->a, create x->b, delete x, create x->b(终态)
    st, _, raw = safe_request("POST", ALIAS_UPDATE, json={
        "actions": [
            {"create_alias": {"alias_name": ALIAS, "collection_name": COLL_A}},
            {"create_alias": {"alias_name": ALIAS, "collection_name": COLL_B}},
            {"delete_alias": {"alias_name": ALIAS}},
            {"create_alias": {"alias_name": ALIAS, "collection_name": COLL_B}},
        ]})
    print(f"chained batch: {st} {raw[:200]}")

    st2, body, raw2 = safe_request("GET", LIST_ALIASES)
    print(f"list aliases: {st2} {raw2[:400]}")
    if st2 == 0 or st2 >= 500:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — alias list {st2}: {raw2[:200]}")
        sys.exit(1)

    targets = alias_targets(body)
    if targets is None:
        print("VERDICT: SCRIPT_ERROR — cannot parse alias list response")
        sys.exit(2)
    if len(targets) != 1 or targets[0] != COLL_B:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — non-atomic partial state: alias bindings {targets}")
        sys.exit(1)

    # 路由验证：count via alias 必须 == b 的 7
    st3, body3, raw3 = safe_request("POST", COUNT_PATH.format(name=ALIAS), json={"exact": True})
    print(f"count via alias: {st3} {raw3[:200]}")
    cnt = (body3.get("result") or {}).get("count") if isinstance(body3, dict) else None
    if st3 != 200 or cnt != 7:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — alias routed to wrong target: count={cnt}")
        sys.exit(1)

    # 幂等重放同一批次两次 → 终态不变
    st, _, raw = safe_request("POST", ALIAS_UPDATE, json={
        "actions": [
            {"delete_alias": {"alias_name": ALIAS}},
            {"create_alias": {"alias_name": ALIAS, "collection_name": COLL_B}},
        ]})
    print(f"replay: {st} {raw[:150]}")
    _, body4, raw4 = safe_request("GET", LIST_ALIASES)
    t4 = alias_targets(body4)
    if t4 != [COLL_B]:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — replay changed state: {t4}")
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
