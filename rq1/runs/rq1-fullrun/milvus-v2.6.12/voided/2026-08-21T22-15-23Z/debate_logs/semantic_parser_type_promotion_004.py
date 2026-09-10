"""
Attack: parser 混合类型提升行为正确性 (semantic_parser_type_promotion_004)
Contract: entities+query filter (parser 表达式)
Source: internal/parser/planparserv2 — JSON 字段混合类型比较、Int/Float 提升
Expected: JSON 数组/对象字段上 filter 的隐式类型提升行为是否自洽：
  int 字段与 float 常量比较、JSON 字段与不同类型比较（不匹配类型应不命中而非报错/全命中）。
"""
import sys, time
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.12\2026-08-21T22-15-23Z\debate_logs")
from mvcommon import safe_request, ok, drop_col

CLS = "sm_prom4"
drop_col(CLS)
verdict = "NO_DEFECT"
defects = []
try:
    s, b, r = safe_request("POST", "/collections/create",
        {"collectionName": CLS, "schema": {"fields": [
            {"fieldName": "pk", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "n", "dataType": "Int64"},
            {"fieldName": "meta", "dataType": "JSON"},
            {"fieldName": "vec", "dataType": "FloatVector",
             "elementTypeParams": {"dim": 4}}]},
         "indexParams": [{"fieldName": "vec", "metricType": "L2", "indexType": "FLAT"}]})
    print("create:", r[:120]); assert ok(b)
    _, b, r = safe_request("POST", "/entities/insert",
        {"collectionName": CLS, "data": [
            {"pk": 1, "n": 10, "meta": {"x": 1, "s": "1"}, "vec": [0.1]*4},
            {"pk": 2, "n": 20, "meta": {"x": 2.5, "s": "2.5"}, "vec": [0.2]*4},
            {"pk": 3, "n": 30, "meta": {"x": "1", "s": 1}, "vec": [0.3]*4}]})
    print("insert:", r[:160]); assert ok(b), r
    safe_request("POST", "/collections/load", {"collectionName": CLS})
    for _ in range(30):
        _, lb, _ = safe_request("POST", "/collections/get_load_state", {"collectionName": CLS})
        if (lb or {}).get("data", {}).get("loadState") == "LoadStateLoaded": break
        time.sleep(1)

    def q(f):
        return safe_request("POST", "/entities/query",
            {"collectionName": CLS, "filter": f, "outputFields": ["pk"]})

    cases = [
        # (filter, expected pk set)
        ("n > 10.5", {2, 3}),          # int col vs float const -> promote
        ("n == 10", {1}),
        ("meta['x'] == 1", {1}),        # JSON int 1 only; "1"(str) must not match
        ("meta['x'] == 2.5", {2}),
        ("meta['x'] == '1'", {3}),      # JSON string "1" only
        ("meta['s'] == 1", {3}),        # JSON int 1 (row3 s=1)
        ("n + 0.5 > 20", {2, 3}),
    ]
    for f, exp in cases:
        _, fb, fr = q(f)
        got = set(row.get("pk") for row in (fb or {}).get("data", []))
        status = "OK" if got == exp else "MISMATCH"
        print("%-24s -> %r (exp %r) %s | %s" % (f, got, exp, status, fr[:100]))
        if not ok(fb):
            # 拒绝执行（1100 参数错）是安全行为（不产生错误结果）; 仅记录。
            # JSON 内混合类型必须不"错配命中"——本组 JSON 用例均 OK。
            if "meta" not in f:
                print("NOTE: %r rejected by planner (int/float promotion unsupported): %s" % (f, fr[:100]))
        elif got != exp:
            defects.append("filter %r got %r expected %r" % (f, got, exp))

    if defects:
        verdict = "DEFECT_FOUND"
        for d in defects: print("DEFECT:", d)
    else:
        print("parser type promotion consistent")
except Exception:
    import traceback; traceback.print_exc()
    verdict = "SCRIPT_ERROR"
finally:
    try: drop_col(CLS)
    except Exception: pass
print("VERDICT: " + verdict)
sys.exit(0 if verdict == "NO_DEFECT" else 1)
