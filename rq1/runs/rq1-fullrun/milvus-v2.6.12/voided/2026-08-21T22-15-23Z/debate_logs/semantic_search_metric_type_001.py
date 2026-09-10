"""
Attack: search 请求 metric_type 与 collection index metric 冲突的语义 (semantic_search_metric_type_001)
Contract: milvus_range_entities_search_001 (searchParams); 契约未定义 metric_type 冲突行为
Source: internal/util/segcore/plan.go:109 (NewSearchRequest: metric mismatch -> error)
GT-relevant: entities+search / metric_type
Expected: Type4 语义缺陷候选 — 大小写不一致 (l2 vs L2) 报 "not match" 而非归一化;
          冲突 metric 返回 65535 (fail to search on QueryNode) 而非参数级 1100 — 错误分类粗糙。
Verify (distance 语义): L2 值域 >=0 单调; 指定冲突 metric 若被静默接受则距离语义错误。
"""
import sys, time
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.12\2026-08-21T22-15-23Z\debate_logs")
from mvcommon import safe_request, ok, create_col, drop_col, wait_load

CLS = "sm_metric1"
drop_col(CLS)
verdict = "NO_DEFECT"
defects = []
try:
    s, b, r = create_col(CLS, metric="L2")
    print("create:", r[:120]); assert ok(b)
    _, b, r = safe_request("POST", "/entities/insert",
        {"collectionName": CLS, "data": [
            {"pk": 1, "vec": [0.1, 0.2, 0.3, 0.4]},
            {"pk": 2, "vec": [0.9, 0.8, 0.7, 0.6]},
            {"pk": 3, "vec": [-0.1, -0.2, -0.3, -0.4]}]})
    assert ok(b)
    safe_request("POST", "/collections/load", {"collectionName": CLS})
    wait_load(CLS)

    q = [[0.1, 0.2, 0.3, 0.4]]
    def search(metric):
        sp = {"metric_type": metric} if metric else {}
        return safe_request("POST", "/entities/search",
            {"collectionName": CLS, "data": q, "limit": 3, "searchParams": sp})

    # baseline L2
    _, bl, rl = search("L2"); print("L2:", rl[:220])
    base = {d["pk"]: d["distance"] for d in bl.get("data", [])}
    if not (base.get(1, 1) <= 1e-6 and base.get(2, 9) > 1):
        defects.append("L2 baseline distance wrong: %r" % base)

    # conflicting metric must NOT silently succeed with wrong-distance results
    for m in ("COSINE", "IP", "l2"):
        _, bm, rm = search(m); print("%s:" % m, rm[:200])
        if ok(bm):
            dist = {d["pk"]: d["distance"] for d in bm.get("data", [])}
            if m == "l2" and abs(dist.get(1, -1)) <= 1e-6:
                defects.append("lowercase 'l2' silently accepted (case-sensitive mismatch with L2 index)")
            elif m in ("COSINE", "IP"):
                defects.append("conflicting metric %s accepted, distances=%r (index=L2)" % (m, dist))
        else:
            code = bm.get("code")
            print("  rejected code=%s" % code)
            # 参数级错误应为 1100; 65535 是 QueryNode 运行期错误 — 记录不判定

    if defects:
        verdict = "DEFECT_FOUND"
        for d in defects: print("DEFECT:", d)
    else:
        print("metric conflict semantics consistent")
except Exception:
    import traceback; traceback.print_exc()
    verdict = "SCRIPT_ERROR"
finally:
    try: drop_col(CLS)
    except Exception: pass
print("VERDICT: " + verdict)
sys.exit(0 if verdict == "NO_DEFECT" else 1)
