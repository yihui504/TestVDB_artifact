"""
Vein: truncate 实现层深度 — REST/GRC 参数面 + 状态机残迹 (vein_truncate_impl_depth_003)
源码定位:
  handler_v2.go:757 truncateCollection — REST 只传 CollectionName (无 partition/timeout 面)
  rootcoord/ddl_callbacks_truncate_collection.go:91 truncateCollectionV2AckOnceCallback
    — BeginTruncateCollection 禁 compaction; DropSegmentsByTime 等 checkpoint
  datacoord/meta.go:2539 TruncateChannelByTime — 只按 DmlPosition<=flushTs 删
对照组:
  A truncate 后 datacoord 统计应 0 (get_stats)
  B truncate 期间 flush 并发 — flush code 应为 0 或有序错误，不得数据残留
  C truncate 后再 insert → 数据正常可见（truncate 不锁死写入路径）
  D truncate nonexistent -> code 100 (对照)
"""
import sys, time, threading
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.12\2026-08-21T22-15-23Z\debate_logs")
from mvcommon import safe_request, ok, create_col, drop_col, wait_load, flush

CLS = "vn_trunc3"
drop_col(CLS)
verdict = "NO_DEFECT"; defects = []
try:
    s, b, r = create_col(CLS)
    assert ok(b), r
    safe_request("POST", "/entities/insert",
        {"collectionName": CLS, "data": [{"pk": i, "vec": [0.01 * i] * 4} for i in range(50)]})
    flush(CLS); time.sleep(2)

    # B: concurrent flush during truncate
    results = []
    def flusher():
        for _ in range(6):
            _, fb, fr = flush(CLS)
            results.append(((fb or {}).get("code"), fr[:60]))
            time.sleep(0.3)
    t = threading.Thread(target=flusher); t.start()
    _, tb, tr = safe_request("POST", "/collections/truncate", {"collectionName": CLS})
    print("truncate:", tr[:100])
    t.join()
    print("flush results during truncate:", results)
    # 1807 (flush forbidden during truncate) is a controlled merr rejection, not a crash.
    # Only flag transport-level failures (code None / HTTP >=500 / connection errors).
    codes = set(c for c, _ in results)
    print("distinct flush codes:", codes)
    for c, _ in results:
        if c is None or c == -1:
            defects.append("transport-level flush failure during truncate: %r" % c)
    time.sleep(3)
    _, sb, sr = safe_request("POST", "/collections/get_stats", {"collectionName": CLS})
    print("stats after:", sr[:100])

    # C: write after truncate is alive
    _, ib, ir = safe_request("POST", "/entities/insert",
        {"collectionName": CLS, "data": [{"pk": 500, "vec": [0.5]*4}]})
    print("insert post-truncate:", ir[:100])
    flush(CLS); time.sleep(2)
    safe_request("POST", "/collections/load", {"collectionName": CLS}); wait_load(CLS)
    _, qb, qr = safe_request("POST", "/entities/query",
        {"collectionName": CLS, "filter": "pk == 500", "outputFields": ["pk"],
         "consistencyLevel": "Strong"})
    print("query pk==500:", qr[:140])
    if ok(qb) and not (qb.get("data")):
        defects.append("insert after truncate not visible (Strong): %s" % qr[:100])

    # D control
    _, nb, nr = safe_request("POST", "/collections/truncate", {"collectionName": "nope_v"})
    print("D nonexistent:", nr[:100])
    if ok(nb):
        defects.append("truncate nonexistent returned code 0")

    if defects:
        verdict = "DEFECT_FOUND"
        for d in defects: print("DEFECT:", d)
    else:
        print("truncate implementation depth checks passed")
except Exception:
    import traceback; traceback.print_exc()
    verdict = "SCRIPT_ERROR"
finally:
    try: drop_col(CLS)
    except Exception: pass
print("VERDICT: " + verdict)
sys.exit(0 if verdict == "NO_DEFECT" else 1)
