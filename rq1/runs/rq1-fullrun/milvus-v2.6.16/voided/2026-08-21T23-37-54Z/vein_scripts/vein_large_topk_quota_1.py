# script_id: vein_large_topk_quota_1
# Vein: discover-then-deepen — large_topk 配额路径 (2.6 新) 成熟度 + 源码定位
# 对照组: 普通 collection（limit 16384 上限） vs large_topk collection（1000000 上限）
# 关注: (a) 越界错误的 code/消息质量 (b) 上限切换是否即时生效（alter 后无需 load 刷新?）
# Constraints: milvus_range_entities_search_001, milvus_range_entities_search_003
# source_url: .milvus-src-2616 (quota check: internal/proxy task_search? topk range msg), doc_version: unknown
import os, sys, time
import requests

BASE = os.environ.get("TESTVDB_DB_URL")
TOKEN = os.environ.get("TESTVDB_DB_TOKEN", "root:Milvus")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
H = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}

def sr(path, body=None):
    try:
        r = requests.post(BASE + "/v2/vectordb/" + path, json=body if body is not None else {}, headers=H, timeout=120)
        raw = r.text
        try:
            b = r.json()
        except Exception:
            b = None
        return r.status_code, b, raw
    except Exception as e:
        return -1, None, str(e)

CL_N = "vn_ltk_ctl"
CL_L = "vn_ltk_trt"
SCHEMA = {"fields": [
    {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
    {"fieldName": "vector", "dataType": "FloatVector", "elementTypeParams": {"dim": "4"}}]}

def cleanup():
    for c in [CL_N, CL_L]:
        try: sr("collections/drop", {"collectionName": c})
        except Exception: pass

def search(name, **kw):
    b = {"collectionName": name, "data": [[0.1, 0.2, 0.3, 0.4]], "consistencyLevel": "Strong"}
    b.update(kw)
    return sr("entities/search", b)

def code_of(b):
    return b.get("code") if isinstance(b, dict) else None

def main():
    defects = []
    cleanup(); time.sleep(1)
    for c in [CL_N, CL_L]:
        sr("collections/create", {"collectionName": c, "schema": SCHEMA})
    # order matters: alter query_mode BEFORE index (702 gate blocks alter after index)
    s, b, raw = sr("collections/alter_properties", {"collectionName": CL_L, "properties": {"query_mode": "large_topk"}})
    print("setup alter qm:", s, raw[:150])
    if not (isinstance(b, dict) and b.get("code") == 0):
        print("VERDICT: SCRIPT_ERROR"); cleanup(); sys.exit(2)
    for c in [CL_N, CL_L]:
        sr("indexes/create", {"collectionName": c, "indexParams": [
            {"fieldName": "vector", "indexName": "idx", "indexType": "FLAT", "metricType": "L2"}]})
    for c in [CL_N, CL_L]:
        sr("entities/insert", {"collectionName": c, "data": [{"id": i, "vector": [0.1, 0.2, 0.3, 0.4]} for i in range(10)]})
        sr("collections/load", {"collectionName": c})
    time.sleep(2)

    # CONTROL: normal collection boundaries
    print("CTL limit=16384:", code_of(search(CL_N, limit=16384)[1]))
    s, b, raw = search(CL_N, limit=16385)
    print("CTL limit=16385:", s, raw[:160])
    if code_of(b) == 0:
        defects.append(("control: normal mode accepted limit 16385", raw[:120]))
    msg = str((b or {}).get("message"))
    if code_of(b) != 0 and "16384" not in msg:
        defects.append(("control: over-limit message omits bound", msg[:120]))

    # TREATMENT: large_topk boundaries
    s, b, raw = search(CL_L, limit=1000000)
    print("TRT limit=1000000:", s, raw[:160])
    if code_of(b) != 0:
        defects.append(("large_topk rejected limit=1000000 exactly", raw[:150]))
    s, b, raw = search(CL_L, limit=1000001)
    print("TRT limit=1000001:", s, raw[:160])
    if code_of(b) == 0:
        defects.append(("large_topk ACCEPTED limit=1000001 (over cap)", raw[:150]))
    else:
        msg = str((b or {}).get("message"))
        if "1000000" not in msg:
            defects.append(("large_topk over-cap message omits bound 1000000", msg[:120]))

    # offset+limit window
    s, b, raw = search(CL_L, limit=1, offset=999999)
    print("TRT offset999999+limit1 (==cap):", s, raw[:140])
    if code_of(b) != 0:
        defects.append(("large_topk rejected offset+limit==cap exactly", raw[:120]))
    s, b, raw = search(CL_L, limit=2, offset=999999)
    print("TRT offset999999+limit2 (>cap):", s, raw[:140])
    if code_of(b) == 0:
        defects.append(("large_topk ACCEPTED window 1000001", raw[:120]))

    # immediacy: unset large_topk impossible (no way back)? try alter to "" or other value
    s, b, raw = sr("collections/alter_properties", {"collectionName": CL_L, "properties": {"query_mode": ""}})
    print("RESET alter query_mode='':", s, raw[:180])
    if code_of(b) == 0:
        s2, b2, raw2 = search(CL_L, limit=100000)
        print("RESET limit=100000 after unset attempt:", code_of(b2), raw2[:140])
        if code_of(b2) == 0:
            defects.append(("query_mode set to '' accepted and large limit STILL allowed (state corruption)", raw2[:120]))

    cleanup()
    for d in defects: print("DEFECT:", d)
    if defects:
        print("VERDICT: DEFECT_FOUND"); sys.exit(1)
    print("VERDICT: NO_DEFECT"); sys.exit(0)

try:
    main()
except Exception as e:
    print("EXC:", e)
    try: cleanup()
    except Exception: pass
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
