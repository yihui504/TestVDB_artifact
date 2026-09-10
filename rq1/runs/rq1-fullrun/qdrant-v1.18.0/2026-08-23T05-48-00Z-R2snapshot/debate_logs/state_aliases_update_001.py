# script_id: state_aliases_update_001
# strategy: count_consistency
# endpoint: aliases+update
# Attack: qdrant_state_aliases_update_001 + qdrant_bc_alias_atomic_switch_001
#   (策略1 CRUD 后 COUNT 一致性 × alias 路由切换)
# constraint_ids: qdrant_state_aliases_update_001, qdrant_bc_alias_atomic_switch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
# doc_version: 1.18.x (versioned)
# Blindspot: BS-03 Concurrency State Blindness (alias 路由状态一致性)
"""
State: create collections a (4 pts) and b (2 pts); create alias x -> a;
count via alias == 4; atomic rename alias x -> b; count via alias must be 2.
Verifies count consistency across alias routing switch (behavioral contract
scenario) — after rename, queries via x must hit b exactly.
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
COLL_A = f"st_alias_a_{TS}"
COLL_B = f"st_alias_b_{TS}"
ALIAS  = f"st_alias_x_{TS}"
CREATE_PATH = "/collections/{name}"
ALIAS_UPDATE = "/collections/aliases"
UPSERT_PATH = "/collections/{name}/points?wait=true"
COUNT_PATH = "/collections/{name}/points/count"
DIM = 4

def cleanup():
    # 删集合（qdrant 删目标集合时 alias 会被清理）；再无操作可做，全部 try/except
    for name in (COLL_A, COLL_B):
        try:
            safe_request("DELETE", CREATE_PATH.format(name=name))
        except Exception:
            pass

def count_via(name):
    st, body, raw = safe_request("POST", COUNT_PATH.format(name=name),
                                 json={"exact": True})
    print(f"count[{name}] status={st} raw={raw[:200]}")
    if st != 200 or not isinstance(body, dict):
        return None
    r = body.get("result")
    return r.get("count") if isinstance(r, dict) else None

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
        print(f"upsert {name}: {st} {raw[:150]}")
        if st not in (200, 201):
            ok = False
            break
    if not ok:
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)

    # create alias x -> a
    st, _, raw = safe_request("POST", ALIAS_UPDATE, json={
        "actions": [{"create_alias": {"alias_name": ALIAS, "collection_name": COLL_A}}]})
    print(f"create_alias: {st} {raw[:200]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)
    ca = count_via(ALIAS)
    if ca != 4:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — alias->a expected count 4, got {ca}")
        sys.exit(1)

    # atomic rename alias x -> b (rename_alias keeps same alias name, switches target
    # is done via delete+create in ONE actions batch = the atomic-switch scenario)
    st, _, raw = safe_request("POST", ALIAS_UPDATE, json={
        "actions": [
            {"delete_alias": {"alias_name": ALIAS}},
            {"create_alias": {"alias_name": ALIAS, "collection_name": COLL_B}},
        ]})
    print(f"atomic switch: {st} {raw[:200]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)

    time.sleep(1)
    cb = count_via(ALIAS)
    if cb != 2:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — after switch alias must route to b (count 2), got {cb}")
        sys.exit(1)

    # 原集合计数不受 alias 操作影响（约束：alias 操作原子，不修改 collection 数据）
    ca2, cb2 = count_via(COLL_A), count_via(COLL_B)
    if ca2 != 4 or cb2 != 2:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — alias ops changed collection counts: a={ca2} b={cb2}")
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
