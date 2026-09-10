# script_id: state_range_cc004_strictmode_echo_03
# strategy: state_consistency (策略1 配置持久化 echo × create/update 双路径)
# endpoint: collections+create
# Attack: qdrant_range_collections_create_004 (strict_mode_config.max_resident_memory_percent
#   IN [1,100]) × (a) 合法值 50 create 后状态持久化 echo（GET collection / quotas+get）
#   (b) collections+update 路径越界值 101 是否非法成功 (c) 接受但静默丢弃 = Type4
#   create 侧 accept/reject 已由 boundary_collections_create_06 覆盖（null 判 Type1），
#   本脚本只攻 update 路径 + 持久化状态面
# constraint_ids: qdrant_range_collections_create_004
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
"""
State: create strict_mode_config{enabled:true, max_resident_memory_percent:50} (valid)
-> accepted 200. Then verify persisted state:
  - GET /collections/{c}: does config echo strict_mode values? (echo-with-different-value = Type4)
  - PATCH collections+update max_resident_memory_percent=101 (out of range): 200 = Type1
  - PATCH enabled=false (valid): if accepted (200) but NO state anywhere (collection config)
    reflects strict_mode at all while create+update both accepted it => silently dropped
    config = Type4 candidate (evidence printed for judge).
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
COLL = f"st_smc_{TS}"
CREATE = f"/collections/{COLL}"

try:
    st, body, raw = safe_request("PUT", CREATE, json={
        "vectors": {"size": 4, "distance": "Cosine"},
        "strict_mode_config": {"enabled": True, "max_resident_memory_percent": 50},
    })
    print(f"create strict_mode 50: {st} {raw[:300]}")
    if st == 500:
        print("DEFECT detail (Type3): 500 on valid strict_mode create")
        report("DEFECT_FOUND", 1)
    if st not in (200, 201):
        print("setup create failed (not defect)")
        report("SCRIPT_ERROR", 2)

    # state echo after create
    st, body, raw = safe_request("GET", CREATE)
    print(f"get after create: {st} {raw[:800]}")
    has_strict_in_collection = "strict" in (raw or "").lower()
    smc_val = None
    if isinstance(body, dict):
        cfg = (body.get("result") or {}).get("config") or {}
        smc_val = cfg.get("strict_mode_config")
    print(f"strict_mode in collection GET: text_match={has_strict_in_collection} parsed={smc_val}")
    if isinstance(smc_val, dict) and "max_resident_memory_percent" in smc_val \
            and smc_val.get("max_resident_memory_percent") not in (50, None):
        print(f"DEFECT detail (Type4): created max_resident=50 but config echoes {smc_val}")
        report("DEFECT_FOUND", 1)

    # update path: out-of-range 101 must be rejected (mirror of create-side validation)
    st, body, raw = safe_request("PATCH", CREATE, json={
        "strict_mode_config": {"enabled": True, "max_resident_memory_percent": 101}})
    print(f"patch max_resident=101: {st} {raw[:300]}")
    if st == 200:
        print("DEFECT detail (Type1): max_resident_memory_percent=101 accepted on update (range [1,100])")
        report("DEFECT_FOUND", 1)
    if st >= 500:
        print("DEFECT detail (Type3): 5xx on out-of-range update")
        report("DEFECT_FOUND", 1)

    # update path: valid value accepted? and does any state persist it?
    st, body, raw = safe_request("PATCH", CREATE, json={
        "strict_mode_config": {"enabled": True, "max_resident_memory_percent": 30}})
    print(f"patch max_resident=30: {st} {raw[:300]}")
    patch_accepted = (st == 200)

    st2, body2, raw2 = safe_request("GET", CREATE)
    print(f"get after patch: {st2} {raw2[:800]}")
    st3, body3, raw3 = safe_request("GET", "/quotas")
    print(f"quotas: {st3} {(raw3 or '')[:400]}")
    reflected = "strict" in ((raw2 or "") + (raw3 or "")).lower()

    if patch_accepted and not has_strict_in_collection and not reflected:
        print("DEFECT detail (Type4): strict_mode_config accepted on create(200) and update(200) "
              "but reflected in NEITHER collection config NOR quotas — accepted config silently dropped")
        report("DEFECT_FOUND", 1)
    if not patch_accepted and st < 500:
        # update rejects the same param create accepts: state-machine asymmetry (informational,
        # not auto-defect: judge decides against deprecation note in contract)
        print("NOTE: create accepts strict_mode_config but update rejects it (asymmetry)")

    print("state checks complete")
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
