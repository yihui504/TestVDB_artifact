# -*- coding: utf-8 -*-
"""
Attack: 浮点求和顺序敏感性 — 同一对向量多次查询距离稳定性 + 数据顺序无关性 (semantic_r2_distance_stability_04)
Contract: milvus entities+search; 距离计算应为确定性函数
Strategy: metamorphic
Expected: Type4 — 同一 (query, target) 对重复查询 R 次距离应 bit-stable（spread==0，
          容忍 <=1 ULP）；不同插入顺序的同向量集距离应一致（排序后误差 <1e-6）。
"""
import sys, math, random
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.12\2026-08-21T22-15-23Z\debate_logs")
from mvcommon import safe_request, ok, drop_col, wait_load

random.seed(3)
DIM = 64
N = 15
R = 8

def norm(v):
    n = math.sqrt(sum(x*x for x in v)); return [x/n for x in v]

vecs = [norm([random.gauss(0, 1) for _ in range(DIM)]) for _ in range(N)]
query = norm([random.gauss(0, 1) for _ in range(DIM)])

def make(cls, order):
    drop_col(cls)
    s, b, r = safe_request("POST", "/collections/create", {
        "collectionName": cls,
        "schema": {"fields": [
            {"fieldName": "pk", "dataType": "Int64", "isPrimary": True, "autoID": False},
            {"fieldName": "vec", "dataType": "FloatVector",
             "elementTypeParams": {"dim": DIM}}]},
        "indexParams": [{"fieldName": "vec", "indexName": "vec_idx",
                         "metricType": "COSINE", "indexType": "FLAT"}]})
    assert ok(b), "create failed: " + r[:150]
    _, bi, ri = safe_request("POST", "/entities/insert", {"collectionName": cls, "data": [
        {"pk": i, "vec": vecs[i]} for i in order]})
    assert ok(bi), "insert failed: " + ri[:150]
    safe_request("POST", "/collections/load", {"collectionName": cls})
    wait_load(cls)

def search(cls):
    _, b, r = safe_request("POST", "/entities/search", {
        "collectionName": cls, "data": [query], "limit": N,
        "searchParams": {"metric_type": "COSINE"}})
    assert ok(b), "search failed: " + r[:200]
    return {d["pk"]: d["distance"] for d in b["data"]}

verdict = "NO_DEFECT"
defects = []
try:
    make("sm_r2_st_a", list(range(N)))  # ascending insert order
    # repeat-stability on same collection
    runs = [search("sm_r2_st_a") for _ in range(R)]
    base = runs[0]
    spreads = {}
    for pk in base:
        vals = [run.get(pk) for run in runs if pk in run]
        uniq = set(vals)
        if len(uniq) > 1:
            spreads[pk] = (min(uniq), max(uniq))
    print("repeat-stability: %d/%d pks with >1 distinct distance across %d runs" % (
        len(spreads), N, R))
    for pk, (lo, hi) in list(spreads.items())[:5]:
        print("  pk=%d min=%.10g max=%.10g spread=%.3g" % (pk, lo, hi, hi - lo))
        if hi - lo > 1e-9:
            defects.append("non-deterministic distance pk=%d spread=%.3g across identical queries" % (pk, hi - lo))

    # order-independence: reversed insert order
    make("sm_r2_st_b", list(reversed(range(N))))
    alt = search("sm_r2_st_b")
    worst = 0.0
    for pk in base:
        if pk not in alt:
            defects.append("pk=%d missing in reversed-order collection result" % pk)
            continue
        worst = max(worst, abs(base[pk] - alt[pk]))
    print("order-independence worst |delta| = %.6g" % worst)
    if worst > 1e-6:
        defects.append("distance depends on insertion order: worst delta %.6g" % worst)

    if defects:
        verdict = "DEFECT_FOUND"
        for d in defects[:10]: print("DEFECT:", d)
    else:
        print("distance computation deterministic and order-independent")
except Exception:
    import traceback; traceback.print_exc()
    verdict = "SCRIPT_ERROR"
finally:
    for c in ("sm_r2_st_a", "sm_r2_st_b"):
        try: drop_col(c)
        except Exception: pass
print("VERDICT: " + verdict)
sys.exit(0 if verdict == "NO_DEFECT" else 1)
