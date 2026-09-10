# script_id: state_bc_query_visibility_wait_false_09
# strategy: state_consistency (策略3 upsert 幂等/可见性 × wait=false 最终一致性窗口)
# endpoint: points+upsert (block: chunk_collections+create-2of2 via bc_create_query_visibility_001)
# Attack: behavioral_contracts::qdrant_bc_create_query_visibility_001 参数族扩展
#   (novel candidate)：wait=true 已知立即可见（script 08 regression），本脚本攻
#   wait=false 分支 —— 200-accepted 的异步 upsert 是否在有限窗口内变成可见
#   （by-design 只豁免"错误不记录"，不豁免"数据丢失"）
# constraint_ids: qdrant_type_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points
# doc_version: 1.18.x (versioned)
# exploration_target: novel_candidate (wait=false visibility — issue 未报分支)
"""
State: create dim=4 Cosine; upsert 3 points with wait=false (accepted 200).
Poll (0.5s interval, 20s cap): exact count must reach 3 AND query nearest v(201)
must return 201 top. If an upsert that returned 200 NEVER becomes visible
(final count < 3 after window) => accepted-but-lost write = Type4.
Also: delete with wait=false then poll — point must eventually disappear
(count reach 2); permanent visibility of deleted point = Type4.
"""
import requests, json, sys, os, time

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("TESTVDB_DB_URL not set")
    print("VERDICT: SCRIPT_ERROR")
    sys.exit(2)
AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")


def safe_request(method, path, **kwargs):
    url = f"{BASE_URL}{path}"
    headers = kwargs.pop("headers", {"Content-Type": "application/json"})
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER
    try:
        resp = requests.request(method, url, headers=headers, timeout=60, **kwargs)
        status = resp.status_code
        text = resp.text
        try:
            body = resp.json() if text else None
        except (json.JSONDecodeError, ValueError):
            body = None
        return status, body, text
    except requests.exceptions.RequestException as e:
        print(f"REQUEST_ERROR: {e}")
        return 0, None, ""


def report(verdict, code):
    print(f"VERDICT: {verdict}")
    sys.exit(code)


def exact_count():
    st, body, raw = safe_request("POST", COUNT, json={"exact": True})
    if isinstance(body, dict):
        return (body.get("result") or {}).get("count")
    return None


V201 = [1.0, 0.0, 0.0, 0.0]
V202 = [0.0, 1.0, 0.0, 0.0]
V203 = [0.0, 0.0, 1.0, 0.0]
TS = str(int(time.time())) + str(os.getpid() % 1000)
COLL = f"st_bcvf_{TS}"
CREATE = f"/collections/{COLL}"
COUNT = f"{CREATE}/points/count"
QUERY = f"{CREATE}/points/query"
POLL_WINDOW = 20.0

try:
    st, body, raw = safe_request("PUT", CREATE, json={
        "vectors": {"size": 4, "distance": "Cosine"}})
    print(f"create: {st} {raw[:150]}")
    if st != 200:
        report("SCRIPT_ERROR", 2)

    # async upserts (wait=false), each individually accepted
    accepted = 0
    for pid, vec in ((201, V201), (202, V202), (203, V203)):
        st, body, raw = safe_request("PUT", f"{CREATE}/points?wait=false",
                                     json={"points": [{"id": pid, "vector": vec}]})
        print(f"upsert {pid} wait=false: {st} {raw[:120]}")
        if st == 200:
            accepted += 1
        elif st >= 500:
            print(f"DEFECT detail (Type3): 5xx on wait=false upsert: {st}")
            report("DEFECT_FOUND", 1)
    print(f"accepted upserts: {accepted}/3")
    if accepted < 3:
        print("NOTE: some wait=false upserts rejected 4xx (legit backpressure), "
              "only accepted ones must become visible")

    # poll for eventual visibility
    deadline = time.time() + POLL_WINDOW
    visible = False
    while time.time() < deadline:
        c = exact_count()
        print(f"poll count: {c}")
        if accepted == 3 and c == 3:
            visible = True
            break
        if c is not None and c >= accepted and accepted < 3:
            visible = True
            break
        time.sleep(0.5)
    print(f"final count after window: {exact_count()} (accepted={accepted})")
    if not visible:
        print(f"DEFECT detail (Type4): {accepted} upserts returned 200 with wait=false "
              f"but never all became visible within {POLL_WINDOW}s (lost writes)")
        report("DEFECT_FOUND", 1)

    # query visibility of the async-written point
    if accepted == 3:
        st, body, raw = safe_request("POST", QUERY, json={
            "query": {"nearest": V201}, "limit": 3, "with_payload": False})
        print(f"query v201: {st} {raw[:300]}")
        hits = []
        if isinstance(body, dict):
            hits = body.get("result") or []
        if not hits or hits[0].get("id") != 201:
            print(f"DEFECT detail (Type4): async point 201 not query-visible though count==3: "
                  f"{[h.get('id') for h in hits]}")
            report("DEFECT_FOUND", 1)

        # async delete eventual invisibility
        st, body, raw = safe_request("POST", f"{CREATE}/points/delete?wait=false",
                                     json={"points": [201]})
        print(f"delete 201 wait=false: {st} {raw[:120]}")
        deadline = time.time() + POLL_WINDOW
        gone = False
        while time.time() < deadline:
            c = exact_count()
            print(f"poll count after delete: {c}")
            if c == 2:
                gone = True
                break
            time.sleep(0.5)
        if not gone:
            print("DEFECT detail (Type4): wait=false delete returned 200 but point "
                  "remained visible past poll window")
            report("DEFECT_FOUND", 1)

    print("wait=false eventual-visibility checks passed")
    report("NO_DEFECT", 0)
except SystemExit:
    raise
except Exception as e:
    print(f"UNEXPECTED_ERROR: {type(e).__name__}: {e}")
    report("SCRIPT_ERROR", 2)
finally:
    try:
        safe_request("DELETE", CREATE)
    except Exception:
        pass
