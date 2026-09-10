"""
Attack: search ids 模式语义正确性 (semantic_search_ids_mode_002)
Contract: entities+search ids/data 互斥 (handler_v2.go:1513)
Source: internal/proxy/impl.go handleIfSearchByPK — ids 转 requery->placeholder->向量 search
Expected defect candidates:
 1) ids 搜索与 data 搜索等价性: 每个返回条目的 distance 应等于用该实体向量做 data 搜索的 distance
 2) 多 id 时结果顺序/重复语义 (实测 2 ids x limit2 返回 4 行 = 每个 id 独立 topk)
 3) varchar pk 的数字 id 自动转字符串 (convertIDsToSchemapbIDs 接受数字转 %v 字符串) — 类型混淆
"""
import sys, time
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.12\2026-08-21T22-15-23Z\debate_logs")
from mvcommon import safe_request, ok, create_col, drop_col, wait_load

CLS = "sm_ids2"; CLSV = "sm_ids2v"
drop_col(CLS); drop_col(CLSV)
verdict = "NO_DEFECT"
defects = []
try:
    s, b, r = create_col(CLS)
    assert ok(b), r
    _, b, r = safe_request("POST", "/entities/insert",
        {"collectionName": CLS, "data": [
            {"pk": 1, "vec": [0.1, 0.2, 0.3, 0.4]},
            {"pk": 2, "vec": [0.9, 0.8, 0.7, 0.6]}]})
    assert ok(b)
    safe_request("POST", "/collections/load", {"collectionName": CLS})
    wait_load(CLS)

    # ids search
    _, ib, ir = safe_request("POST", "/entities/search",
        {"collectionName": CLS, "ids": [1, 2], "limit": 2})
    print("ids search:", ir[:300])
    ids_res = (ib or {}).get("data", [])
    # data search with each entity's vector as query
    _, d1, dr1 = safe_request("POST", "/entities/search",
        {"collectionName": CLS, "data": [[0.1, 0.2, 0.3, 0.4]], "limit": 2})
    _, d2, dr2 = safe_request("POST", "/entities/search",
        {"collectionName": CLS, "data": [[0.9, 0.8, 0.7, 0.6]], "limit": 2})
    print("data q1:", dr1[:200]); print("data q2:", dr2[:200])
    m1 = {row["pk"]: row["distance"] for row in d1.get("data", [])}
    m2 = {row["pk"]: row["distance"] for row in d2.get("data", [])}
    for row in ids_res:
        pk, dist = row.get("pk"), row.get("distance")
        ref = m1.get(pk, m2.get(pk))
        if ref is None:
            defects.append("ids-search pk %r not found in either data-search result" % pk)
        elif abs(ref - dist) > 1e-4:
            defects.append("ids-search distance mismatch pk=%r ids=%r data=%r" % (pk, dist, ref))
    if len(ids_res) != 4:
        print("NOTE: ids-search rows=%d (2 ids x limit 2 => nq-per-id semantics)" % len(ids_res))

    # varchar pk: numeric ids silently coerced to strings
    s, b, r = safe_request("POST", "/collections/create",
        {"collectionName": CLSV, "schema": {"fields": [
            {"fieldName": "pk", "dataType": "VarChar", "isPrimary": True,
             "elementTypeParams": {"max_length": "64"}},
            {"fieldName": "vec", "dataType": "FloatVector",
             "elementTypeParams": {"dim": 4}}]},
         "indexParams": [{"fieldName": "vec", "metricType": "L2", "indexType": "FLAT"}]})
    print("create varchar:", r[:120]); assert ok(b)
    _, b, r = safe_request("POST", "/entities/insert",
        {"collectionName": CLSV, "data": [{"pk": "42", "vec": [0.1, 0.2, 0.3, 0.4]},
                                          {"pk": "abc", "vec": [0.9, 0.8, 0.7, 0.6]}]})
    assert ok(b), r
    safe_request("POST", "/collections/load", {"collectionName": CLSV})
    wait_load(CLSV)
    _, nb, nr = safe_request("POST", "/entities/search",
        {"collectionName": CLSV, "ids": [42], "limit": 1})   # 数字而非字符串
    print("varchar pk numeric id 42:", nr[:200])
    if ok(nb) and (nb.get("data")):
        defects.append("VarChar PK: numeric id 42 silently coerced to '42' and matched (type confusion, ids:[42] vs pk '42')")
    # insert pk '0042'? distinct string; numeric 42 must not match it
    _, ib2, ir2 = safe_request("POST", "/entities/search",
        {"collectionName": CLSV, "ids": ["42"], "limit": 1})
    print("varchar pk string id '42':", ir2[:160])

    if defects:
        verdict = "DEFECT_FOUND"
        for d in defects: print("DEFECT:", d)
    else:
        print("ids-mode semantics consistent")
except Exception:
    import traceback; traceback.print_exc()
    verdict = "SCRIPT_ERROR"
finally:
    try: drop_col(CLS); drop_col(CLSV)
    except Exception: pass
print("VERDICT: " + verdict)
sys.exit(0 if verdict == "NO_DEFECT" else 1)
