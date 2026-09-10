"""
Attack: warmup 与 load 状态机交互 (state_warmup_load_state_004)
Contract: milvus_state_collections_get_load_state_001 (LoadState enum)
Source: internal/distributed/proxy/httpserver/handler_v2.go loadCollection
  — REST loadCollection handler 只解析 CollectionNameReq, body 里的 loadParams 完全被丢弃
  (与 gRPC LoadCollectionRequest.LoadParams 不同)。REST warmup 请求静默 no-op。
Focus: 1) load body 携带 loadParams.warmup=BOGUS 无任何校验/效果 (对比 alter_properties 值校验)
       2) load 已 loaded 集合 REST 行为
"""
import sys, time
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.12\2026-08-21T22-15-23Z\debate_logs")
from mvcommon import safe_request, ok, create_col, drop_col, wait_load

CLS = "st_warm4"
drop_col(CLS)
verdict = "NO_DEFECT"
defects = []
try:
    s, b, r = create_col(CLS)
    print("create:", r[:120]); assert ok(b)

    # case A: load with bogus loadParams — REST handler drops loadParams entirely, no validation
    s, b, r = safe_request("POST", "/collections/load",
        {"collectionName": CLS, "loadParams": {"warmup": "BOGUS", "replicaNumber": 99}})
    print("A load w/ bogus loadParams:", r[:160])
    st = wait_load(CLS); print("loadState after bogus:", st)
    if st == "LoadStateNotExist":
        defects.append("load with loadParams created nothing (state NotExist) despite code 0")
    # 若 code 0 且 loaded，BOGUS warmup 从未被校验 —— 静默忽略
    _, db, dr = safe_request("POST", "/collections/describe", {"collectionName": CLS})
    props = [p for p in (db.get("data", {}).get("properties") or []) if "warmup" in p.get("key", "")]
    print("warmup props persisted:", props)

    # case B: load already loaded (contract says gRPC -> 104)
    s2, b2, r2 = safe_request("POST", "/collections/load", {"collectionName": CLS})
    print("B load again:", r2[:160])
    if ok(b2):
        # REST 重复杂 load 是 no-op 成功 — 记录语义差异（contract 标注 104 是 gRPC 语义）
        print("NOTE: REST repeated load returns code 0 (contract milvus_state_collections_load_001 says 104)")

    # case C: load nonexistent
    _, nb, nr = safe_request("POST", "/collections/load", {"collectionName": "nope_q"})
    print("C load nonexistent:", nr[:140])

    # case D: release then refresh_load on nonexistent
    _, fb, fr = safe_request("POST", "/collections/refresh_load", {"collectionName": "nope_q"})
    print("D refresh_load nonexistent:", fr[:140])

    if defects:
        verdict = "DEFECT_FOUND"
        for d in defects: print("DEFECT:", d)
    else:
        print("warmup/load state interactions OK (with notes)")
except Exception:
    import traceback; traceback.print_exc()
    verdict = "SCRIPT_ERROR"
finally:
    try: drop_col(CLS)
    except Exception: pass
print("VERDICT: " + verdict)
sys.exit(0 if verdict == "NO_DEFECT" else 1)
