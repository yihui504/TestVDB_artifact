# script_id: state_bhvr_cc001_fail_no_zombie_05
# strategy: state_consistency (失败路径状态纯度 — 模式 C 依赖链断裂变体)
# endpoint: collections+create
# Attack: assertions::qdrant_behavioral_collections_create_001 (invalid vectors enum =>
#   400 Format error in JSON body) × 失败后不得留下僵尸状态：exists=false / GET 404 /
#   list 不含该名 / 同名合法 create 不被污染
#   前轮只测了 create 侧 status（type_003），本脚本攻失败后的系统状态面
# constraint_ids: qdrant_type_collections_create_003
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
"""
State: PUT create with vectors.distance="bogus" (invalid enum) and named-map form
{"vectors":{"img":{"size":4,"distance":"nope"}}} => both must fail 4xx.
After EACH failure the collection must NOT exist (no zombie): GET 404,
exists=false, collections list does not contain the name. Then a VALID create
with the same name must succeed 200 (name not poisoned by the failed attempt).
Any leftover existence / poisoned name = Type4_StateLogicViolation.
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


TS = str(int(time.time())) + str(os.getpid() % 1000)
COLL = f"st_zmb_{TS}"
CREATE = f"/collections/{COLL}"


def assert_no_zombie(tag):
    st, body, raw = safe_request("GET", CREATE)
    print(f"[{tag}] get: {st} {(raw or '')[:150]}")
    if st != 404:
        print(f"DEFECT detail (Type4): [{tag}] failed create left zombie: GET={st}")
        report("DEFECT_FOUND", 1)
    st, body, raw = safe_request("GET", f"{CREATE}/exists")
    print(f"[{tag}] exists: {st} {(raw or '')[:150]}")
    ex = None
    if isinstance(body, dict):
        ex = (body.get("result") or {}).get("exists")
    if ex is not False:
        print(f"DEFECT detail (Type4): [{tag}] exists endpoint reports exists={ex} after failed create")
        report("DEFECT_FOUND", 1)
    st, body, raw = safe_request("GET", "/collections")
    listed = False
    if isinstance(body, dict):
        listed = COLL in ((body.get("result") or {}).get("collections") or [])
    print(f"[{tag}] in list: {listed}")
    if listed:
        print(f"DEFECT detail (Type4): [{tag}] failed create appears in collections list")
        report("DEFECT_FOUND", 1)


try:
    # variant 1: unnamed vector, invalid distance enum
    st, body, raw = safe_request("PUT", CREATE, json={
        "vectors": {"size": 4, "distance": "bogus"}})
    print(f"create distance=bogus: {st} {(raw or '')[:300]}")
    if st == 200:
        print("DEFECT detail (Type1): invalid distance enum accepted with 200")
        report("DEFECT_FOUND", 1)
    if st >= 500:
        print("DEFECT detail (Type3): 5xx on invalid enum create")
        report("DEFECT_FOUND", 1)
    assert_no_zombie("v1-enum")

    # variant 2: named-vectors map form, invalid enum on inner param
    st, body, raw = safe_request("PUT", CREATE, json={
        "vectors": {"img": {"size": 4, "distance": "nope"}}})
    print(f"create named distance=nope: {st} {(raw or '')[:300]}")
    if st == 200:
        print("DEFECT detail (Type1): invalid named-vector distance enum accepted with 200")
        report("DEFECT_FOUND", 1)
    if st >= 500:
        print("DEFECT detail (Type3): 5xx on invalid named enum create")
        report("DEFECT_FOUND", 1)
    assert_no_zombie("v2-named-enum")

    # name must be reusable: valid create now succeeds
    st, body, raw = safe_request("PUT", CREATE, json={
        "vectors": {"size": 4, "distance": "Cosine"}})
    print(f"valid create after failures: {st} {(raw or '')[:200]}")
    if st != 200:
        print(f"DEFECT detail (Type4): name poisoned by earlier failed creates: {st} {(raw or '')[:200]}")
        report("DEFECT_FOUND", 1)
    st, body, raw = safe_request("GET", CREATE)
    print(f"final get: {st} {(raw or '')[:200]}")

    print("failure-state purity checks passed")
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
