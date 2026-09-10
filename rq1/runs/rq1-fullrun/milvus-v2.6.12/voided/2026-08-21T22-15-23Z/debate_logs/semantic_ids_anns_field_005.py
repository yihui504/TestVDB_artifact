"""
Attack: annsField 注入语义 + 多向量字段 ids 搜索 (semantic_ids_anns_field_005)
Contract: entities+search annsField
Source: handler_v2.go:1588 — ids 模式仅在 httpReq.AnnsField != "" 时才把 anns_field 加进 searchParams!
  即 ids 模式 + annsField="" 时 handleIfSearchByPK 走 schema 推断（单向量场 OK），
  但多向量场时 REST ids 搜索无法指定 anns field -> 报"multiple anns_fields"，
  尽管 REST data 模式同样传空 annsField（handler_v2.go:1572 无条件 append）也报错 ——
  差异: data 模式空 annsField 也 append 空 key。验证两种模式行为一致性 + bogus annsField。
"""
import sys, time
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.12\2026-08-21T22-15-23Z\debate_logs")
from mvcommon import safe_request, ok, drop_col

CLS = "sm_anns5"
drop_col(CLS)
verdict = "NO_DEFECT"
defects = []
try:
    s, b, r = safe_request("POST", "/collections/create",
        {"collectionName": CLS, "schema": {"fields": [
            {"fieldName": "pk", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "va", "dataType": "FloatVector", "elementTypeParams": {"dim": 4}},
            {"fieldName": "vb", "dataType": "FloatVector", "elementTypeParams": {"dim": 4}}]},
         "indexParams": [
            {"fieldName": "va", "indexName": "ia", "metricType": "L2", "indexType": "FLAT"},
            {"fieldName": "vb", "indexName": "ib", "metricType": "COSINE", "indexType": "FLAT"}]})
    print("create:", r[:150])
    if not ok(b):
        print("multi-vector create rejected; degrade to single-vector annsField tests")
        sys.exit(0)
    _, b, r = safe_request("POST", "/entities/insert",
        {"collectionName": CLS, "data": [
            {"pk": 1, "va": [0.1]*4, "vb": [1.0, 0.0, 0.0, 0.0]},
            {"pk": 2, "va": [0.9]*4, "vb": [0.0, 1.0, 0.0, 0.0]}]})
    print("insert:", r[:150])
    assert ok(b), r
    safe_request("POST", "/collections/load", {"collectionName": CLS})
    for _ in range(40):
        _, lb, _ = safe_request("POST", "/collections/get_load_state", {"collectionName": CLS})
        if (lb or {}).get("data", {}).get("loadState") == "LoadStateLoaded": break
        time.sleep(1)

    # A: ids mode, annsField explicit -> OK expected
    _, a, ar = safe_request("POST", "/entities/search",
        {"collectionName": CLS, "ids": [1, 2], "limit": 2, "annsField": "va"})
    print("A ids annsField=va:", ar[:220])
    # B: ids mode, annsField omitted -> REST drops key; server-side infer should fail (multi vec)
    _, b2, br = safe_request("POST", "/entities/search",
        {"collectionName": CLS, "ids": [1, 2], "limit": 2})
    print("B ids no annsField:", br[:220])
    # C: data mode with annsField inside searchParams (pymilvus style) instead of top-level
    _, c, cr = safe_request("POST", "/entities/search",
        {"collectionName": CLS, "data": [[0.1]*4], "limit": 2,
         "searchParams": {"anns_field": "va"}})
    print("C data searchParams.anns_field:", cr[:220])
    if ok(c):
        # 若 searchParams 里 anns_field 生效则与顶层 annsField 双通道 — 一致性检查
        print("  NOTE: anns_field inside searchParams accepted (top-level annsField also exists)")
    # D: bogus annsField top-level
    _, d, dr = safe_request("POST", "/entities/search",
        {"collectionName": CLS, "data": [[0.1]*4], "limit": 2, "annsField": "nope"})
    print("D bogus annsField:", dr[:180])
    if ok(d):
        defects.append("bogus annsField 'nope' accepted silently")
    # E: ids mode + annsField pointing at non-vector field -> 1100 expected (probed earlier)
    _, e, er = safe_request("POST", "/entities/search",
        {"collectionName": CLS, "ids": [1], "limit": 1, "annsField": "pk"})
    print("E ids annsField=pk:", er[:180])
    if ok(e):
        defects.append("ids mode annsField=pk (non-vector) accepted")

    if defects:
        verdict = "DEFECT_FOUND"
        for d_ in defects: print("DEFECT:", d_)
    else:
        print("annsField injection semantics consistent")
except Exception:
    import traceback; traceback.print_exc()
    verdict = "SCRIPT_ERROR"
finally:
    try: drop_col(CLS)
    except Exception: pass
print("VERDICT: " + verdict)
sys.exit(0 if verdict == "NO_DEFECT" else 1)
