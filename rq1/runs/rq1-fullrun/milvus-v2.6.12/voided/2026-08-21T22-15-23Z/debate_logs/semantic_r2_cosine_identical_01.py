# -*- coding: utf-8 -*-
"""
Attack: COSINE metric 数学不变量 — identical 向量自查询距离分布 (semantic_r2_cosine_identical_01)
Contract: milvus search endpoint (entities+search); metric_type=COSINE 距离域 [0,2]（相似度1-距离）
Source: contract search constraint (metric math domain, doc_version unknown)
Strategy: search_correctness / metamorphic
Blindspot: BS-05 Documentation Drift
Expected: Type4 — identical 向量 distance 应为 0（|d|<ε）；批量 ≥100 个 normalized 128 维
          向量各自查自身，任何 distance > 1.0+ε 或 < -ε 即数学不变量违规。
"""
import sys, json, random, math
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.12\2026-08-21T22-15-23Z\debate_logs")
from mvcommon import safe_request, ok, drop_col, wait_load

CLS = "sm_r2_cos1"
DIM = 128
N = 120
EPS = 1e-4

random.seed(42)
vecs = []
for i in range(N):
    v = [random.gauss(0, 1) for _ in range(DIM)]
    n = math.sqrt(sum(x * x for x in v))
    vecs.append([x / n for x in v])

drop_col(CLS)
verdict = "NO_DEFECT"
defects = []
try:
    s, b, r = safe_request("POST", "/collections/create", {
        "collectionName": CLS,
        "schema": {"fields": [
            {"fieldName": "pk", "dataType": "Int64", "isPrimary": True, "autoID": False},
            {"fieldName": "vec", "dataType": "FloatVector",
             "elementTypeParams": {"dim": DIM}}]},
        "indexParams": [{"fieldName": "vec", "indexName": "vec_idx",
                         "metricType": "COSINE", "indexType": "FLAT"}]})
    print("create:", r[:120])
    assert ok(b), "create failed"
    # insert in batches
    for st_i in range(0, N, 60):
        batch = [{"pk": j, "vec": vecs[j]} for j in range(st_i, min(st_i + 60, N))]
        _, bi, ri = safe_request("POST", "/entities/insert",
                                 {"collectionName": CLS, "data": batch})
        assert ok(bi), "insert failed: " + ri[:150]
    _, bl, _ = safe_request("POST", "/collections/load", {"collectionName": CLS})
    wait_load(CLS)

    stats = []
    for i in range(N):
        _, bs, rs = safe_request("POST", "/entities/search", {
            "collectionName": CLS, "data": [vecs[i]], "limit": 1,
            "searchParams": {"metric_type": "COSINE"}})
        if not ok(bs):
            print("search %d failed: %s" % (i, rs[:150]))
            defects.append("self-search %d rejected: %s" % (i, rs[:100]))
            continue
        d = bs["data"][0]["distance"]
        pk = bs["data"][0].get("pk")
        stats.append(abs(d-1.0))
        if pk != i:
            defects.append("self-search %d returned pk=%s (not itself)" % (i, pk))
        if abs(d - 1.0) > 1e-3:
            defects.append("identical-vector COSINE similarity drift |d-1|>1e-3: id=%d d=%.8g" % (i, d))

    if stats:
        stats.sort()
        print("identical-distance distribution: n=%d min=%.8g p50=%.8g max=%.8g mean=%.8g" % (
            len(stats), stats[0], stats[len(stats)//2], stats[-1],
            sum(stats)/len(stats)))
        over = sum(1 for d in stats if d > EPS)
        print("count(|d-1|>eps=%.0e): %d / %d" % (EPS, over, len(stats)))
        for d in stats[-5:]:
            print("  top drift |d-1|: %.10g" % d)
    if defects:
        verdict = "DEFECT_FOUND"
        for d in defects[:10]:
            print("DEFECT:", d)
    else:
        print("COSINE identical-distance invariant holds")
except Exception:
    import traceback; traceback.print_exc()
    verdict = "SCRIPT_ERROR"
finally:
    try: drop_col(CLS)
    except Exception: pass
print("VERDICT: " + verdict)
sys.exit(0 if verdict == "NO_DEFECT" else 1)
