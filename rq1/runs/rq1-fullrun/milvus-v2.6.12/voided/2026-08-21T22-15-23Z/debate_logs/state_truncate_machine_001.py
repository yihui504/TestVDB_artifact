"""
Attack: truncate 状态机一致性 (Strategy 1 count + truncate 语义, 单元 state_truncate_machine_001)
Contract: milvus_state_collections_truncate_001 / milvus_inv_truncate_count_001
Source: .milvus-src-2612/internal/distributed/proxy/httpserver/handler_v2.go
Expected defect type: Type4_StateLogicViolation
Covers: truncate 后 rowCount==0 / schema 保留 / load state 保留 / index 保留
"""
import sys, time, json
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.12\2026-08-21T22-15-23Z\debate_logs")
from mvcommon import safe_request, ok, create_col, drop_col, wait_load, flush

CLS = "st_trunc_m1"
drop_col(CLS)
verdict = "NO_DEFECT"
defects = []
try:
    s, b, r = create_col(CLS)
    print("create:", r[:200]); assert ok(b), "create failed"
    # insert 3, flush -> stats rowCount==3
    s, b, r = safe_request("POST", "/entities/insert",
        {"collectionName": CLS, "data": [
            {"pk": 1, "vec": [0.1, 0.2, 0.3, 0.4]},
            {"pk": 2, "vec": [0.9, 0.8, 0.7, 0.6]},
            {"pk": 3, "vec": [0.5, 0.5, 0.5, 0.5]}]})
    print("insert:", r[:150]); assert ok(b)
    flush(CLS); time.sleep(3)
    s, b, r = safe_request("POST", "/collections/get_stats", {"collectionName": CLS})
    print("stats pre:", r)
    rc0 = b.get("data", {}).get("rowCount")
    if rc0 != 3:
        defects.append("pre-truncate rowCount=%r expected 3" % rc0)

    _, db, dr = safe_request("POST", "/collections/describe", {"collectionName": CLS})
    schema_pre = json.dumps(db.get("data", {}).get("fields"), sort_keys=True)
    _, lb, lr = safe_request("POST", "/collections/get_load_state", {"collectionName": CLS})
    ls_pre = (lb or {}).get("data", {}).get("loadState")
    print("load pre:", ls_pre)

    # truncate on NOT loaded collection (contract only live-confirmed loaded)
    s, b, r = safe_request("POST", "/collections/truncate", {"collectionName": CLS})
    print("truncate:", r[:200])
    if not ok(b):
        defects.append("truncate on not-loaded collection failed: %s" % r[:150])
    time.sleep(3)
    _, b2, r2 = safe_request("POST", "/collections/get_stats", {"collectionName": CLS})
    print("stats post:", r2)
    rc1 = b2.get("data", {}).get("rowCount")
    if rc1 != 0:
        defects.append("post-truncate rowCount=%r expected 0" % rc1)
    # query Strong must see nothing
    _, qb, qr = safe_request("POST", "/entities/query",
        {"collectionName": CLS, "filter": "pk >= 0", "outputFields": ["pk"],
         "consistencyLevel": "Strong"})
    n = len((qb or {}).get("data", []))
    if n != 0:
        defects.append("post-truncate query returned %d rows (Strong)" % n)
    # schema preserved
    _, db2, _ = safe_request("POST", "/collections/describe", {"collectionName": CLS})
    schema_post = json.dumps(db2.get("data", {}).get("fields"), sort_keys=True)
    if schema_pre != schema_post:
        defects.append("schema changed after truncate")
    # index preserved
    _, ib, ir = safe_request("POST", "/indexes/describe",
        {"collectionName": CLS, "indexName": "vec_idx"})
    print("index post:", ir[:250])
    if not ok(ib) or (ib.get("data") or [{}])[0].get("indexState") != "Finished":
        defects.append("index not preserved after truncate: %s" % ir[:150])
    # load state unchanged
    _, lb2, _ = safe_request("POST", "/collections/get_load_state", {"collectionName": CLS})
    ls_post = (lb2 or {}).get("data", {}).get("loadState")
    if ls_pre != ls_post:
        defects.append("loadState changed by truncate: %s -> %s" % (ls_pre, ls_post))
    # truncate nonexistent -> must be 100 not success
    _, nb, nr = safe_request("POST", "/collections/truncate", {"collectionName": "nope_zz"})
    print("truncate nonexistent:", nr[:150])
    if ok(nb):
        defects.append("truncate nonexistent collection returned code 0")
    if defects:
        verdict = "DEFECT_FOUND"
        for d in defects:
            print("DEFECT:", d)
    else:
        print("all truncate invariants held")
except Exception as e:
    import traceback; traceback.print_exc()
    verdict = "SCRIPT_ERROR"
finally:
    drop_col(CLS)
print("VERDICT: " + verdict)
sys.exit(0 if verdict == "NO_DEFECT" else 1)
