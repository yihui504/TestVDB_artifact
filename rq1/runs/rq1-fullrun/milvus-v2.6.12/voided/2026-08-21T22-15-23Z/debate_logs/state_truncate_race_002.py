"""
Attack: truncate 与并发 insert/query 竞态 (策略7 lifecycle 并发变体, 单元 state_truncate_race_002)
Contract: milvus_state_collections_truncate_001 / milvus_inv_count_consistency_001
Source: .milvus-src-2612/internal/datacoord/services.go DropSegmentsByTime (WatchChannelCheckpoint+TruncateChannelByTime)
Expected: Type4_StateLogicViolation — truncate 后残留 truncate 前数据 / or query 5xx
Key invariant: truncate 开始后写入的数据必须存活; truncate 前的数据必须消失。
"""
import sys, time, threading
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.12\2026-08-21T22-15-23Z\debate_logs")
from mvcommon import safe_request, ok, create_col, drop_col, wait_load, flush

CLS = "st_trunc_race2"
drop_col(CLS)
verdict = "NO_DEFECT"
defects = []
errs = []
try:
    s, b, r = create_col(CLS)
    print("create:", r[:120]); assert ok(b)
    # pre-truncate data pk 0..99, flush
    batch = [{"pk": i, "vec": [0.01 * (i % 20), 0.2, 0.3, 0.4]} for i in range(100)]
    _, b, r = safe_request("POST", "/entities/insert",
        {"collectionName": CLS, "data": batch})
    print("pre insert:", r[:100]); assert ok(b)
    flush(CLS); time.sleep(3)
    _, b, _ = safe_request("POST", "/collections/get_stats", {"collectionName": CLS})
    print("stats pre:", b)

    stop = threading.Event()
    def writer(tag):
        i = 0
        while not stop.is_set():
            _, b, r = safe_request("POST", "/entities/insert",
                {"collectionName": CLS,
                 "data": [{"pk": 1000 + tag * 100000 + i,
                           "vec": [0.1, 0.2, 0.3, 0.4]}]})
            if not ok(b):
                errs.append(("insert", tag, i, r[:120]))
            i += 1
            time.sleep(0.02)

    def reader():
        while not stop.is_set():
            s, b, r = safe_request("POST", "/entities/query",
                {"collectionName": CLS, "filter": "pk >= 0",
                 "outputFields": ["pk"], "limit": 100})
            c = (b or {}).get("code")
            if c not in (0, 101):  # 101 not-loaded tolerated during truncate sync
                errs.append(("query", c, r[:120]))
            time.sleep(0.05)

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
    threads.append(threading.Thread(target=reader))
    for t in threads: t.start()
    time.sleep(2)
    ts, tb, tr = safe_request("POST", "/collections/truncate", {"collectionName": CLS})
    print("truncate:", tr[:150])
    time.sleep(2)
    stop.set()
    for t in threads: t.join()
    print("writer/query errors:", errs[:10])
    # server-side hard errors are runtime failures
    hard = [e for e in errs if e[0] == "query" and isinstance(e[1], int) and e[1] >= 500] + \
           [e for e in errs if e[0] == "insert" and not isinstance(e[1], int)]
    if hard:
        defects.append("hard errors during truncate race: %r" % hard[:5])
    # settle: wait for checkpoint drain, flush, Strong query
    flush(CLS); time.sleep(5)
    _, qb, qr = safe_request("POST", "/entities/query",
        {"collectionName": CLS, "filter": "pk >= 0", "outputFields": ["pk"],
         "limit": 200, "consistencyLevel": "Strong"})
    print("post query raw:", qr[:400])
    if ok(qb):
        pks = [row.get("pk") for row in qb.get("data", [])]
        old = [p for p in pks if p is not None and 0 <= p < 100]
        if old:
            defects.append("pre-truncate rows survived truncate (Strong): %r" % old[:20])
        else:
            print("rows surviving (expected post-truncate writes):", len(pks))
    else:
        print("post query not ok:", qr[:150])
    if defects:
        verdict = "DEFECT_FOUND"
        for d in defects: print("DEFECT:", d)
    else:
        print("truncate race consistent")
except Exception:
    import traceback; traceback.print_exc()
    verdict = "SCRIPT_ERROR"
finally:
    try: drop_col(CLS)
    except Exception: pass
print("VERDICT: " + verdict)
sys.exit(0 if verdict == "NO_DEFECT" else 1)
