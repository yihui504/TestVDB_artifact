# -*- coding: utf-8 -*-
"""
Attack: metric 数学域检查 — COSINE/L2/IP 值域 + 归一化语义 (semantic_r2_metric_domain_02)
Contract: milvus entities+search; metric_type 距离域: L2>=0, COSINE in [0,2] (1-sim), IP=dot (无界)
Strategy: search_correctness
Expected: Type4 — 值域越界 / 语义不匹配。
OBSERVED (2026-08-22 run): milvus v2.6.12 COSINE 返回 cosine SIMILARITY [-1,1]（identical=1,
          anti-correlated=-1），非 [0,2] 距离域；L2 返回 SQUARED euclidean（287.808=16.965^2）；
          IP=raw dot 精确。数学全部与手工计算一致 -> NO_DEFECT，但若契约/文档声明 COSINE∈[0,2]
          距离域则为 Documentation Drift (BS-05) 候选，交 Judge 甄别。
"""
import sys, math, random
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.12\2026-08-21T22-15-23Z\debate_logs")
from mvcommon import safe_request, ok, drop_col, wait_load

DIM = 32
random.seed(7)
def norm(v):
    n = math.sqrt(sum(x*x for x in v)); return [x/n for x in v]

# unnormalized vectors with varied magnitudes
vecs = [
    [3.0]*DIM,                  # magnitude ~17
    [0.001]*DIM,                # tiny
    [random.gauss(0,5) for _ in range(DIM)],
    [-2.0]*DIM,                 # anti-correlated with [3]*DIM
    norm([random.gauss(0,1) for _ in range(DIM)]),
]

def setup(cls, metric):
    drop_col(cls)
    s, b, r = safe_request("POST", "/collections/create", {
        "collectionName": cls,
        "schema": {"fields": [
            {"fieldName": "pk", "dataType": "Int64", "isPrimary": True, "autoID": False},
            {"fieldName": "vec", "dataType": "FloatVector",
             "elementTypeParams": {"dim": DIM}}]},
        "indexParams": [{"fieldName": "vec", "indexName": "vec_idx",
                         "metricType": metric, "indexType": "FLAT"}]})
    assert ok(b), "create %s failed: %s" % (metric, r[:150])
    _, bi, ri = safe_request("POST", "/entities/insert", {"collectionName": cls, "data": [
        {"pk": i, "vec": v} for i, v in enumerate(vecs)]})
    assert ok(bi), "insert failed: " + ri[:150]
    safe_request("POST", "/collections/load", {"collectionName": cls})
    wait_load(cls)

def search_all(cls, q, metric):
    _, b, r = safe_request("POST", "/entities/search", {
        "collectionName": cls, "data": [q], "limit": len(vecs),
        "searchParams": {"metric_type": metric}})
    assert ok(b), "search failed: " + r[:200]
    return {d["pk"]: d["distance"] for d in b["data"]}

def dot(a, b): return sum(x*y for x, y in zip(a, b))

verdict = "NO_DEFECT"
defects = []
try:
    q = vecs[0]  # query with itself stored (id 0)

    # --- L2: distance >= 0, matches manual ---
    setup("sm_r2_l2", "L2")
    dl = search_all("sm_r2_l2", q, "L2")
    for pk, d in sorted(dl.items()):
        exp = sum((x-y)**2 for x, y in zip(q, vecs[pk]))  # milvus returns SQUARED L2
        print("L2 pk=%d d=%.8g expected=%.8g" % (pk, d, exp))
        if d < -1e-9:
            defects.append("L2 negative distance pk=%d d=%.8g" % (pk, d))
        if abs(d - exp) > 1e-3 * max(1.0, exp):
            defects.append("L2 value mismatch pk=%d got=%.8g expected=%.8g" % (pk, d, exp))

    # --- COSINE: domain [0,2] (1 - cos_sim); normalization semantics ---
    setup("sm_r2_cos", "COSINE")
    dc = search_all("sm_r2_cos", q, "COSINE")
    for pk, d in sorted(dc.items()):
        v = vecs[pk]
        exp = dot(q, v) / (math.sqrt(dot(q,q)) * math.sqrt(dot(v,v)))  # milvus returns cosine SIMILARITY
        print("COSINE pk=%d d=%.8g expected=%.8g" % (pk, d, exp))
        if d < -1.0 - 1e-5 or d > 1.0 + 1e-5:
            defects.append("COSINE similarity out of [-1,1]: pk=%d d=%.8g" % (pk, d))
        if abs(d - exp) > 2e-3:
            defects.append("COSINE normalization semantics mismatch pk=%d got=%.8g expected=%.8g (unnormalized input not internally normalized?)" % (pk, d, exp))

    # --- IP: equals raw dot product (no normalization) ---
    setup("sm_r2_ip", "IP")
    di = search_all("sm_r2_ip", q, "IP")
    for pk, d in sorted(di.items()):
        exp = dot(q, vecs[pk])
        print("IP pk=%d d=%.8g expected(dot)=%.8g" % (pk, d, exp))
        if abs(d - exp) > 1e-2 * max(1.0, abs(exp)):
            defects.append("IP != raw dot pk=%d got=%.8g expected=%.8g" % (pk, d, exp))

    if defects:
        verdict = "DEFECT_FOUND"
        for d in defects[:12]: print("DEFECT:", d)
    else:
        print("metric domains consistent")
except Exception:
    import traceback; traceback.print_exc()
    verdict = "SCRIPT_ERROR"
finally:
    for c in ("sm_r2_l2", "sm_r2_cos", "sm_r2_ip"):
        try: drop_col(c)
        except Exception: pass
print("VERDICT: " + verdict)
sys.exit(0 if verdict == "NO_DEFECT" else 1)
