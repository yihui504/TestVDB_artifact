# state_r2_upsert_delete_race_007.py
# Attack: 并发 upsert/delete/query 同 ID 竞态 — 最终 rowCount 一致性 + query 结果漂移
# Blindspot: BS-03 | Strategy: concurrent | Param: delete_id
# Constraint: milvus_inv_count_consistency, milvus_behavioral_error_envelope_001
# Source: https://github.com/milvus-io/milvus/blob/v2.3.22/internal/distributed/proxy/httpserver/handler_v2.go (v2.3.22)
import os, threading, time
import requests

BASE = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530")
H = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}
CLS = "r2_race_007"
NIDS = 50
ROUNDS = 10

_tls = threading.local()

def sess():
    if not hasattr(_tls, "s"):
        _tls.s = requests.Session()
        _tls.s.headers.update(H)
    return _tls.s

def req(method, path, body=None):
    try:
        r = sess().request(method, BASE + "/" + path, json=body, timeout=30)
        try:
            b = r.json()
        except Exception:
            b = None
        return r.status_code, b, r.text
    except Exception as e:
        return -1, None, str(e)

def code(b):
    return b.get("code") if isinstance(b, dict) else None

def main():
    try:
        req("POST", "v2/vectordb/collections/drop", {"collectionName": CLS})
        s, b, raw = req("POST", "v2/vectordb/collections/create",
                        {"collectionName": CLS, "schema": {"fields": [
                            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
                            {"fieldName": "vector", "dataType": "FloatVector",
                             "elementTypeParams": {"dim": 4}}]},
                         "indexParams": [{"fieldName": "vector", "indexName": "idx",
                                          "metricType": "L2",
                                          "params": {"index_type": "FLAT"}}]})
        print("create:", s, raw[:200])
        if code(b) != 200:
            print("VERDICT: SCRIPT_ERROR"); return
        req("POST", "v2/vectordb/entities/insert",
            {"collectionName": CLS, "data": [{"id": i, "vector": [0.1, 0.2, 0.3, 0.4]}
                                             for i in range(NIDS)]})
        time.sleep(1)

        errs = []      # runtime failures (5xx / 65535 / conn reset)
        lock = threading.Lock()

        def upserter():
            for r_ in range(ROUNDS):
                s, b, raw = req("POST", "v2/vectordb/entities/upsert",
                                {"collectionName": CLS, "data": [
                                    {"id": i, "vector": [0.2, 0.2, 0.3, 0.4]} for i in range(NIDS)]})
                if s >= 500 or code(b) == 65535:
                    with lock:
                        errs.append(("upsert", r_, s, code(b), raw[:150]))
                time.sleep(0.02)

        def deleter():
            for r_ in range(ROUNDS):
                # delete even ids, then re-insert to restore
                s, b, raw = req("POST", "v2/vectordb/entities/delete",
                                {"collectionName": CLS, "filter": "id % 2 == 0"})
                if s >= 500 or code(b) == 65535:
                    with lock:
                        errs.append(("delete", r_, s, code(b), raw[:150]))
                time.sleep(0.02)
                s, b, raw = req("POST", "v2/vectordb/entities/insert",
                                {"collectionName": CLS, "data": [
                                    {"id": i, "vector": [0.1, 0.2, 0.3, 0.4]}
                                    for i in range(0, NIDS, 2)]})
                if s >= 500 or code(b) == 65535:
                    with lock:
                        errs.append(("reinsert", r_, s, code(b), raw[:150]))

        def querier():
            for r_ in range(ROUNDS * 2):
                s, b, raw = req("POST", "v2/vectordb/entities/query",
                                {"collectionName": CLS, "filter": "id >= 0", "limit": NIDS + 10,
                                 "outputFields": ["id"]})
                c = code(b)
                if s >= 500 or c == 65535:
                    with lock:
                        errs.append(("query", r_, s, c, raw[:150]))
                elif c == 200:
                    rows = (b or {}).get("data") or []
                    ids = [row.get("id") for row in rows]
                    dup = len(ids) - len(set(ids))
                    if dup > 0:
                        with lock:
                            errs.append(("query-duplicate-ids", r_, s, c, f"dups={dup}"))
                time.sleep(0.02)

        ts = [threading.Thread(target=f) for f in (upserter, deleter, querier)]
        for t in ts: t.start()
        for t in ts: t.join()

        # eventual consistency wait, then final count check
        time.sleep(8)
        s, b, raw = req("POST", "v2/vectordb/collections/get_stats", {"collectionName": CLS})
        rowc = ((b or {}).get("data") or {}).get("rowCount") if code(b) == 200 else None
        s, b, raw2 = req("POST", "v2/vectordb/entities/query",
                         {"collectionName": CLS, "filter": "id >= 0", "limit": 200,
                          "outputFields": ["id"]})
        qn = len((b or {}).get("data") or []) if code(b) == 200 else -1
        print(f"final: rowCount={rowc} query_count={qn} expected={NIDS}")
        print("runtime errors:", errs)

        if errs:
            for e_ in errs:
                print("SUSPECT:", e_)
            print("VERDICT: DEFECT_FOUND")
        elif rowc not in (None, NIDS) or qn not in (-1, NIDS):
            print("VERDICT: DEFECT_FOUND")
        else:
            print("VERDICT: NO_DEFECT")
    except Exception as e:
        print("script error:", repr(e))
        print("VERDICT: SCRIPT_ERROR")
    finally:
        try:
            req("POST", "v2/vectordb/collections/drop", {"collectionName": CLS})
        except Exception:
            pass

if __name__ == "__main__":
    main()
