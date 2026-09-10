"""
Vein: ids 转换链 (REST []interface{} -> schemapb.IDs -> requery -> placeholder) 校验成熟度
vein_ids_conversion_chain_002
源码定位:
  internal/distributed/proxy/httpserver/utils.go:179 convertIDsToSchemapbIDs
    — VarChar PK 分支: int64/int/float64 一律 fmt.Sprintf("%v") 转字符串 (类型混淆入口)
  internal/proxy/impl.go handleIfSearchByPK — duplicate 检查在 REST ids 已去重语义之外
对照组:
  A(对照) Int64 PK, ids=[42] 正常命中
  B(实验) VarChar PK, 数字 42 → 命中 '42' (类型混淆)
  C(实验) VarChar PK, float 42.5 → '%v'='42.5' 可命中字符串 '42.5'
  D(对照) Int64 PK, string "42" → strconv 解析命中 (文档化行为)
  E(实验) VarChar PK, float 42.0 → '%v'='42' 命中 '42' (浮点整数值静默匹配字符串)
"""
import sys, time
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.12\2026-08-21T22-15-23Z\debate_logs")
from mvcommon import safe_request, ok, create_col, drop_col, wait_load

CI = "vn_ids_i"; CV = "vn_ids_v"
drop_col(CI); drop_col(CV)
verdict = "NO_DEFECT"; defects = []
try:
    idx = [{"fieldName": "vec", "metricType": "L2", "indexType": "FLAT"}]
    # Int64 control
    s, b, r = create_col(CI)
    assert ok(b)
    safe_request("POST", "/entities/insert",
        {"collectionName": CI, "data": [{"pk": 42, "vec": [0.1]*4}]})
    safe_request("POST", "/collections/load", {"collectionName": CI}); wait_load(CI)
    _, ab, ar = safe_request("POST", "/entities/search",
        {"collectionName": CI, "ids": ["42"], "limit": 1})
    print("A Int64 pk ids=['42']:", ar[:140], "(documented strconv coercion)")

    # VarChar experiment
    s, b, r = safe_request("POST", "/collections/create",
        {"collectionName": CV, "schema": {"fields": [
            {"fieldName": "pk", "dataType": "VarChar", "isPrimary": True,
             "elementTypeParams": {"max_length": "64"}},
            {"fieldName": "vec", "dataType": "FloatVector",
             "elementTypeParams": {"dim": 4}}]}, "indexParams": idx})
    assert ok(b), r
    safe_request("POST", "/entities/insert",
        {"collectionName": CV, "data": [
            {"pk": "42", "vec": [0.1]*4}, {"pk": "42.5", "vec": [0.2]*4}]})
    safe_request("POST", "/collections/load", {"collectionName": CV}); wait_load(CV)
    for label, idv in [("B numeric 42", 42), ("C float 42.5", 42.5), ("E float 42.0", 42.0)]:
        _, xb, xr = safe_request("POST", "/entities/search",
            {"collectionName": CV, "ids": [idv], "limit": 2})
        hit = bool((xb or {}).get("data"))
        print("%-14s -> hit=%s %s" % (label, hit, xr[:120]))
        if hit:
            defects.append("%s: non-string id %r coerced and matched VarChar pk (convertIDsToSchemapbIDs Sprintf formatting)" % (label, idv))

    if defects:
        verdict = "DEFECT_FOUND"
        for d in defects: print("DEFECT:", d)
    else:
        print("ids conversion chain consistent")
except Exception:
    import traceback; traceback.print_exc()
    verdict = "SCRIPT_ERROR"
finally:
    try: drop_col(CI); drop_col(CV)
    except Exception: pass
print("VERDICT: " + verdict)
sys.exit(0 if verdict == "NO_DEFECT" else 1)
