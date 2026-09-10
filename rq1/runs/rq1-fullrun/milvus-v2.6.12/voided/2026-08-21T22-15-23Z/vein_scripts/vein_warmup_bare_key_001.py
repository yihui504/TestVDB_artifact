"""
Vein: discover-then-deepen — warmup 裸键 "warmup" 校验成熟度 (vein_warmup_bare_key_001)
源码定位:
  pkg/common/common.go:339-351  IsWarmupKey = field(bare 'warmup') + collection(4 个分级键)
  internal/proxy/task.go:459-468 validateWarmupPolicyForProperties — alter 路径有完整校验
  internal/proxy/impl.go AlterCollection(创建/alter) vs createCollection REST 入口
对照组设计:
  A(对照) alter_properties {"warmup":"sync"} released  -> 应被拒 (task.go:463 裸键仅 field 级)
  B(实验) collections/create properties {"warmup":"sync"} -> 校验是否同源（同一 validate 函数?）
  C(实验) create properties {"warmup.vectorIndex":"ASYNC"} -> 实测 create 期不校验值(已证)
  D(对照) field 级 elementTypeParams {"warmup":"BOGUS"} -> field schema 路径校验
"""
import sys, time
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.12\2026-08-21T22-15-23Z\debate_logs")
from mvcommon import safe_request, ok, drop_col

C = "vn_warm1"; C2 = "vn_warm1b"; C3 = "vn_warm1c"
for x in (C, C2, C3): drop_col(x)
verdict = "NO_DEFECT"; defects = []
try:
    idx = [{"fieldName": "vec", "metricType": "L2", "indexType": "FLAT"}]
    vecf = {"fieldName": "vec", "dataType": "FloatVector", "elementTypeParams": {"dim": 4}}
    pk = {"fieldName": "pk", "dataType": "Int64", "isPrimary": True}

    # A control: alter bare key on released collection
    safe_request("POST", "/collections/create",
        {"collectionName": C, "schema": {"fields": [pk, vecf]}, "indexParams": idx})
    _, ab, ar = safe_request("POST", "/collections/alter_properties",
        {"collectionName": C, "properties": {"warmup": "sync"}})
    print("A alter bare warmup:", ar[:180])

    # B: create with bare warmup property (same validation path?)
    _, bb, br = safe_request("POST", "/collections/create",
        {"collectionName": C2, "schema": {"fields": [pk, vecf]}, "indexParams": idx,
         "properties": {"warmup": "sync"}})
    print("B create bare warmup:", br[:180])
    if ok(bb):
        defects.append("create properties accepted bare field-level key 'warmup' (alter path rejects it) — validation asymmetry")

    # C regression: create collection-level invalid value
    _, cb, cr = safe_request("POST", "/collections/create",
        {"collectionName": C3, "schema": {"fields": [pk, vecf]}, "indexParams": idx,
         "properties": {"warmup.vectorIndex": "ASYNC"}})
    print("C create warmup.vectorIndex=ASYNC:", cr[:180])
    if ok(cb):
        defects.append("create accepts invalid warmup policy 'ASYNC' (alter path validates via ValidateWarmupPolicy)")

    # D: field-level warmup bogus value in elementTypeParams
    safe_request("POST", "/collections/drop", {"collectionName": C})
    _, db, dr = safe_request("POST", "/collections/create",
        {"collectionName": C, "schema": {"fields": [pk,
            {"fieldName": "vec", "dataType": "FloatVector",
             "elementTypeParams": {"dim": 4, "warmup": "BOGUS"}}]},
         "indexParams": idx})
    print("D field warmup=BOGUS:", dr[:180])

    if defects:
        verdict = "DEFECT_FOUND"
        for d in defects: print("DEFECT:", d)
    else:
        print("warmup validation consistent across paths")
except Exception:
    import traceback; traceback.print_exc()
    verdict = "SCRIPT_ERROR"
finally:
    try:
        for x in (C, C2, C3): drop_col(x)
    except Exception: pass
print("VERDICT: " + verdict)
sys.exit(0 if verdict == "NO_DEFECT" else 1)
