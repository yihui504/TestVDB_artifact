# -*- coding: utf-8 -*-
"""
Attack: 维度×精度交互 — 高维(32768) identical 距离漂移 (semantic_r2_highdim_drift_03)
Contract: milvus entities+search; FloatVector dim 上限 32768
Strategy: search_correctness / metamorphic
Expected: Type4 — 高维下 identical 向量 COSINE 距离应仍 ~0（|d|<1e-3）；
          漂移显著大于低维基线（如 >1e-2）即精度缺陷。
"""
import sys, math, random
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.12\2026-08-21T22-15-23Z\debate_logs")
from mvcommon import safe_request, ok, drop_col, wait_load

random.seed(11)

def norm(v):
    n = math.sqrt(sum(x*x for x in v)); return [x/n for x in v]

verdict = "NO_DEFECT"
defects = []
try:
    for dim, n in ((128, 20), (4096, 10), (32768, 6)):
        cls = "sm_r2_hd%d" % dim
        drop_col(cls)
        vecs = [norm([random.gauss(0, 1) for _ in range(dim)]) for _ in range(n)]
        s, b, r = safe_request("POST", "/collections/create", {
            "collectionName": cls,
            "schema": {"fields": [
                {"fieldName": "pk", "dataType": "Int64", "isPrimary": True, "autoID": False},
                {"fieldName": "vec", "dataType": "FloatVector",
                 "elementTypeParams": {"dim": dim}}]},
            "indexParams": [{"fieldName": "vec", "indexName": "vec_idx",
                             "metricType": "COSINE", "indexType": "FLAT"}]})
        if not ok(b):
            print("dim=%d create rejected: %s" % (dim, r[:150]))
            defects.append("dim=%d create rejected (within 32768 limit)" % dim)
            continue
        _, bi, ri = safe_request("POST", "/entities/insert", {"collectionName": cls, "data": [
            {"pk": i, "vec": v} for i, v in enumerate(vecs)]})
        assert ok(bi), "insert dim=%d failed: %s" % (dim, ri[:150])
        safe_request("POST", "/collections/load", {"collectionName": cls})
        wait_load(cls)
        ds = []
        for i in range(n):
            _, bs, rs = safe_request("POST", "/entities/search", {
                "collectionName": cls, "data": [vecs[i]], "limit": 1,
                "searchParams": {"metric_type": "COSINE"}}, timeout=120)
            if not ok(bs):
                defects.append("dim=%d self-search %d failed: %s" % (dim, i, rs[:100]))
                continue
            d = bs["data"][0]["distance"]
            if bs["data"][0].get("pk") != i:
                defects.append("dim=%d self-search %d returned other pk" % (dim, i))
            ds.append(abs(d - 1.0))
        if ds:
            print("dim=%d identical-distance: n=%d min=%.8g max=%.8g mean=%.3g" % (
                dim, len(ds), min(ds), max(ds), sum(ds)/len(ds)))
            worst = max(abs(d) for d in ds)
            print("  worst |drift| = %.6g" % worst)
            if worst > 1e-2:
                defects.append("dim=%d identical COSINE drift %.6g exceeds 1e-2 (precision collapse at high dim)" % (dim, worst))
        try: drop_col(cls)
        except Exception: pass
    if defects:
        verdict = "DEFECT_FOUND"
        for d in defects[:10]: print("DEFECT:", d)
    else:
        print("high-dim drift within tolerance")
except Exception:
    import traceback; traceback.print_exc()
    verdict = "SCRIPT_ERROR"
print("VERDICT: " + verdict)
sys.exit(0 if verdict == "NO_DEFECT" else 1)
