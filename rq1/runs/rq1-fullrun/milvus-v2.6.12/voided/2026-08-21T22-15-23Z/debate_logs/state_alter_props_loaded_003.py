"""
Attack: alter properties on loaded collection (state_alter_props_loaded_003)
Contract: milvus_state_collections_alter_properties_001 (warmup blocked on loaded, code 104)
        + milvus_state_collections_load_001 (load already loaded -> 104)
Source: internal/proxy/task.go hasWarmupProp / ValidateWarmupPolicy
Focus: warmup 字段级裸键 "warmup" 在 alter_properties 时被拒 vs 集合级键合法;
       值大小写敏感性("SYNC" 拒 / "sync" 收) — 潜在语义不一致;
       非 warmup 属性在 loaded 下 alter 应成功; drop_properties 同路径。
"""
import sys, time
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.12\2026-08-21T22-15-23Z\debate_logs")
from mvcommon import safe_request, ok, create_col, drop_col, wait_load

CLS = "st_alterp3"
drop_col(CLS)
verdict = "NO_DEFECT"
defects = []
try:
    s, b, r = create_col(CLS)
    print("create:", r[:120]); assert ok(b)
    s, b, r = safe_request("POST", "/collections/load", {"collectionName": CLS})
    print("load:", r[:120]); assert ok(b)
    st = wait_load(CLS); print("loadState:", st)

    def alter(props):
        return safe_request("POST", "/collections/alter_properties",
                            {"collectionName": CLS, "properties": props})

    # case A: collection-level warmup on loaded -> expect 104
    _, b, r = alter({"warmup.vectorIndex": "sync"})
    print("A warmup.vectorIndex on loaded:", r[:160])
    if ok(b):
        defects.append("warmup.vectorIndex alter succeeded on LOADED collection (expected 104)")

    # case B: field-level bare key "warmup" on loaded — spec says only allowed at field level
    _, b, r = alter({"warmup": "sync"})
    print("B bare warmup on loaded:", r[:160])
    if ok(b):
        defects.append("bare field-level key 'warmup' accepted at collection alter_properties (task.go says field-level only)")

    # case C: mmap on loaded -> expect 104 (control)
    _, b, r = alter({"mmap.enabled": "true"})
    print("C mmap on loaded:", r[:160])

    # case D: plain prop on loaded -> expect success
    _, b, r = alter({"ttl.seconds": "77"})
    print("D ttl on loaded:", r[:120])

    # case E: value case-sensitivity — released, "SYNC" (uppercase) vs "sync"
    safe_request("POST", "/collections/release", {"collectionName": CLS})
    _, b, r = alter({"warmup.vectorIndex": "SYNC"})
    print("E warmup=SYNC released:", r[:160])
    if ok(b):
        defects.append("warmup value 'SYNC' accepted (ValidateWarmupPolicy only allows lowercase disable/sync) — case-sensitive contract violated")
    _, b, r = alter({"warmup.vectorIndex": "sync"})
    print("E2 warmup=sync released:", r[:120])
    if not ok(b):
        defects.append("warmup value 'sync' rejected on released collection: %s" % r[:120])

    # case F: invalid policy value disable/sync之外的 on create properties
    _, cb, cr = safe_request("POST", "/collections/create",
        {"collectionName": CLS + "_x", "schema": {"fields": [
            {"fieldName": "pk", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "vec", "dataType": "FloatVector",
             "elementTypeParams": {"dim": 4}}]},
         "indexParams": [{"fieldName": "vec", "metricType": "L2", "indexType": "FLAT"}],
         "properties": {"warmup.vectorIndex": "ASYNC"}})
    print("F create w/ warmup=ASYNC:", cr[:160])
    if ok(cb):
        defects.append("create accepted invalid warmup policy 'ASYNC'")

    if defects:
        verdict = "DEFECT_FOUND"
        for d in defects: print("DEFECT:", d)
    else:
        print("alter props state machine consistent")
except Exception:
    import traceback; traceback.print_exc()
    verdict = "SCRIPT_ERROR"
finally:
    try:
        drop_col(CLS); drop_col(CLS + "_x")
    except Exception: pass
print("VERDICT: " + verdict)
sys.exit(0 if verdict == "NO_DEFECT" else 1)
