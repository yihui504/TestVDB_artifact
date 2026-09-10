"""
Attack: defaultValue fill 语义 (semantic_default_value_fill_003)
Contract: type_constraints (defaultValue); internal/proxy/validate_util.go fillWithValue
Live findings already probed:
  - REST create 接受 elementTypeParams.default_value="77" (字符串下划线形态) 且 code 0,
    但后续 insert 省略该字段报 1804 cast 错误 —— create 期静默接受不可用默认值。
  - 正确形态是 schema.fields[].defaultValue (camelCase, typed)。
本脚本断言: camelCase 省略填充正确; upsert 路径同样填充; 字符串形态 create 是缺陷
(create 应拒绝无法生效的 default_value 而非让 insert 失败)。
"""
import sys, time
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.12\2026-08-21T22-15-23Z\debate_logs")
from mvcommon import safe_request, ok, drop_col

CLS = "sm_dv3"; CLSW = "sm_dv3w"
drop_col(CLS); drop_col(CLSW)
verdict = "NO_DEFECT"
defects = []
try:
    # wrong-form control: string default_value in elementTypeParams accepted at create?
    s, wb, wr = safe_request("POST", "/collections/create",
        {"collectionName": CLSW, "schema": {"fields": [
            {"fieldName": "pk", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "score", "dataType": "Int32",
             "elementTypeParams": {"default_value": "77"}},
            {"fieldName": "vec", "dataType": "FloatVector",
             "elementTypeParams": {"dim": 4}}]},
         "indexParams": [{"fieldName": "vec", "metricType": "L2", "indexType": "FLAT"}]})
    print("create wrong-form:", wr[:140])
    if ok(wb):
        _, ib, ir = safe_request("POST", "/entities/insert",
            {"collectionName": CLSW, "data": [{"pk": 1, "vec": [0.1]*4}]})
        print("insert omitting:", ir[:200])
        if not ok(ib):
            defects.append("create accepted default_value='77' (string form) but insert omitting field fails code=%s: %s"
                           % (ib.get("code"), ir[:120]))

    # correct form
    s, b, r = safe_request("POST", "/collections/create",
        {"collectionName": CLS, "schema": {"fields": [
            {"fieldName": "pk", "dataType": "Int64", "isPrimary": True, "autoID": False},
            {"fieldName": "score", "dataType": "Int32", "defaultValue": 77},
            {"fieldName": "tag", "dataType": "VarChar", "defaultValue": "def",
             "elementTypeParams": {"max_length": "64"}},
            {"fieldName": "vec", "dataType": "FloatVector",
             "elementTypeParams": {"dim": 4}}]},
         "indexParams": [{"fieldName": "vec", "metricType": "L2", "indexType": "FLAT"}]})
    print("create:", r[:160]); assert ok(b), r
    _, b, r = safe_request("POST", "/entities/insert",
        {"collectionName": CLS, "data": [
            {"pk": 1, "vec": [0.1, 0.2, 0.3, 0.4]},
            {"pk": 2, "score": 5, "tag": "hi", "vec": [0.9, 0.8, 0.7, 0.6]}]})
    print("insert:", r[:160]); assert ok(b), r
    safe_request("POST", "/collections/load", {"collectionName": CLS})
    for _ in range(30):
        _, lb, _ = safe_request("POST", "/collections/get_load_state", {"collectionName": CLS})
        if (lb or {}).get("data", {}).get("loadState") == "LoadStateLoaded": break
        time.sleep(1)
    _, qb, qr = safe_request("POST", "/entities/query",
        {"collectionName": CLS, "filter": "pk >= 0", "outputFields": ["pk", "score", "tag"]})
    print("query:", qr[:250])
    rows = {row.get("pk"): row for row in (qb or {}).get("data", [])}
    if rows.get(1, {}).get("score") != 77:
        defects.append("omitted Int32 default: got %r expected 77" % rows.get(1, {}).get("score"))
    if rows.get(1, {}).get("tag") != "def":
        defects.append("omitted VarChar default: got %r expected 'def'" % rows.get(1, {}).get("tag"))
    if rows.get(2, {}).get("score") != 5:
        defects.append("explicit value overwritten: %r" % rows.get(2))

    # upsert path
    _, ub, ur = safe_request("POST", "/entities/upsert",
        {"collectionName": CLS, "data": [{"pk": 1, "vec": [0.2]*4}]})
    print("upsert:", ur[:140])
    time.sleep(2)
    _, qb2, qr2 = safe_request("POST", "/entities/query",
        {"collectionName": CLS, "filter": "pk == 1", "outputFields": ["pk", "score", "tag"]})
    print("after upsert:", qr2[:200])
    row = ((qb2 or {}).get("data") or [{}])[0]
    if row.get("score") != 77:
        defects.append("upsert omitting defaulted field: score=%r expected 77 (insert/upsert default-fill inconsistency)" % row.get("score"))

    if defects:
        verdict = "DEFECT_FOUND"
        for d in defects: print("DEFECT:", d)
    else:
        print("default value fill semantics consistent")
except Exception:
    import traceback; traceback.print_exc()
    verdict = "SCRIPT_ERROR"
finally:
    try: drop_col(CLS); drop_col(CLSW)
    except Exception: pass
print("VERDICT: " + verdict)
sys.exit(0 if verdict == "NO_DEFECT" else 1)
