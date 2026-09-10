# script_id: state_collections_delete_006
# strategy: delete_consistency
# endpoint: collections+delete
# Attack: qdrant_state_collections_delete_001 × 模式C 依赖链断裂 (alias -> collection 依赖)
#   覆盖: 删除带 alias 的 collection 后，经 alias 的所有访问路径状态语义：
#   GET/count 经 alias 必须 404（僵尸 200 = Type4；500/连接重置 = Type3）；
#   同名 recreate 后经 alias 不得返回旧数据；orphan alias 残留只记 OBSERVATION（契约未规定 alias 清理）
# constraint_ids: qdrant_state_collections_delete_001, qdrant_bc_collection_delete_isolation_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned)
"""
Dependency chain: alias -> collection. Delete the collection, then probe every
path through the alias. The alias must never expose deleted data (200 zombie) or
crash the server (5xx). Recreate same-name collection with different data: alias
must not return the OLD 3 points.
"""
import requests, json, sys, os, time

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
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
COLL = f"st_cdel_al_{TS}"
ALIAS = f"st_cdel_alx_{TS}"
DIM = 4

def cleanup():
    try:
        safe_request("POST", "/collections/aliases",
                     json={"actions": [{"delete_alias": {"alias_name": ALIAS}}]})
    except Exception:
        pass
    try:
        safe_request("DELETE", f"/collections/{COLL}")
    except Exception:
        pass

def defect(msg):
    print(msg)
    print("VERDICT: DEFECT_FOUND")
    sys.exit(1)

def count_via(name):
    st, body, raw = safe_request("POST", f"/collections/{name}/points/count", json={"exact": True})
    print(f"count[{name}]: {st} {raw[:200]}")
    if st != 200 or not isinstance(body, dict):
        return st, None
    r = body.get("result")
    return st, (r.get("count") if isinstance(r, dict) else None)

try:
    # setup: collection with 3 points (gen1 marker), alias -> collection
    st, _, raw = safe_request("PUT", f"/collections/{COLL}",
                              json={"vectors": {"size": DIM, "distance": "Cosine"}})
    print(f"create: {st} {raw[:150]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)
    pts = [{"id": i, "vector": [0.1 * (i + 1)] * DIM, "payload": {"gen": 1}} for i in range(3)]
    st, _, raw = safe_request("PUT", f"/collections/{COLL}/points?wait=true", json={"points": pts})
    print(f"upsert gen1: {st} {raw[:150]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)
    st, _, raw = safe_request("POST", "/collections/aliases", json={
        "actions": [{"create_alias": {"alias_name": ALIAS, "collection_name": COLL}}]})
    print(f"create_alias: {st} {raw[:200]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)
    _, c = count_via(ALIAS)
    if c != 3:
        defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — pre-delete alias routing broken: count via alias = {c}, expected 3")

    # delete the underlying collection (alias dependency broken)
    st, _, raw = safe_request("DELETE", f"/collections/{COLL}")
    print(f"delete underlying: {st} {raw[:200]}")
    if st not in (200, 201):
        print(f"OBSERVATION: DELETE returned {st}; continuing")

    # probe 1: GET via alias
    st, _, raw = safe_request("GET", f"/collections/{ALIAS}")
    print(f"get via alias (deleted target): {st} {raw[:200]}")
    if st == 200:
        defect("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — GET via alias returned 200 for deleted collection (zombie via alias)")
    if st >= 500 or st == 0:
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — GET via dangling alias got {st}: {raw[:150]}")

    # probe 2: count via alias
    st, c = count_via(ALIAS)
    if st == 200:
        defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — count via alias returned 200 count={c} for deleted collection (zombie)")
    if st >= 500 or st == 0:
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — count via dangling alias got {st}")

    # probe 3: query via alias
    st, _, raw = safe_request("POST", f"/collections/{ALIAS}/points/query",
                              json={"query": [0.1] * DIM, "limit": 3})
    print(f"query via alias: {st} {raw[:200]}")
    if st == 200:
        defect("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — query via alias returned 200 for deleted collection (zombie)")
    if st >= 500 or st == 0:
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — query via dangling alias got {st}: {raw[:150]}")

    # probe 4: alias list — orphan reporting only (contract silent on cleanup)
    st, body, raw = safe_request("GET", "/collections/aliases")
    print(f"aliases list: {st} {raw[:300]}")
    orphan = False
    if st == 200 and isinstance(body, dict):
        entries = body.get("result", {}).get("aliases", [])
        for e in entries:
            if isinstance(e, dict) and e.get("alias_name") == ALIAS:
                orphan = True
    if orphan:
        print("OBSERVATION: alias still listed after target collection deleted (orphan metadata; contract silent — not scored)")

    # probe 5: recreate same-name with DIFFERENT data; alias must not expose old gen1 points
    st, _, raw = safe_request("PUT", f"/collections/{COLL}",
                              json={"vectors": {"size": DIM, "distance": "Cosine"}})
    print(f"recreate: {st} {raw[:150]}")
    if st not in (200, 201):
        defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — recreate failed {st}: {raw[:150]}")
    pts2 = [{"id": 100 + i, "vector": [0.3] * DIM, "payload": {"gen": 2}} for i in range(2)]
    st, _, raw = safe_request("PUT", f"/collections/{COLL}/points?wait=true", json={"points": pts2})
    print(f"upsert gen2: {st} {raw[:150]}")
    time.sleep(0.5)
    st, c = count_via(ALIAS)
    if st == 200 and c == 3:
        defect("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — alias resolves to OLD deleted data (3 gen1 points) after recreate")
    if st >= 500 or st == 0:
        defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — count via alias after recreate got {st}")
    if st == 200 and c == 2:
        print("OBSERVATION: alias survived delete and routes to recreated collection (coherent, count=2 matches new data)")

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
