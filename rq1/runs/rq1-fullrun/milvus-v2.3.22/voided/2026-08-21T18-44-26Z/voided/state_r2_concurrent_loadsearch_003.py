# state_r2_concurrent_loadsearch_003.py
# Attack: 并发 load/search 竞态 — 多线程 load 完成即 search，收集失败模式与 code 分布
# Blindspot: BS-03 Concurrency Blindness | Strategy: concurrent | Param: load
# Constraint: milvus_state_search_001, milvus_inv_load_lifecycle
# Source: https://github.com/milvus-io/milvus/blob/v2.3.22/internal/distributed/proxy/httpserver/handler_v2.go (v2.3.22)
import os, threading, time
from collections import Counter
import requests

BASE = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530")
H = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}
CLS = "r2_conc_ls_003"
NTHREADS = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10"))

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
            {"collectionName": CLS, "data": [{"id": i, "vector": [0.1, 0.2, 0.3, 0.4]} for i in range(20)]})
        req("POST", "v2/vectordb/collections/release", {"collectionName": CLS})
        time.sleep(0.5)

        results = []  # (thread, iter, http, code, msg) per observation
        lock = threading.Lock()
        start = threading.Barrier(NTHREADS)

        def worker(tid):
            start.wait()
            obs = []
            # each thread: load -> immediate search x3
            s, b, raw = req("POST", "v2/vectordb/collections/load", {"collectionName": CLS})
            obs.append((tid, "load", s, code(b), raw[:120]))
            for k in range(3):
                s, b, raw = req("POST", "v2/vectordb/entities/search",
                                {"collectionName": CLS, "data": [[0.1, 0.2, 0.3, 0.4]], "limit": 5})
                c = code(b)
                n = len((b or {}).get("data") or []) if c == 200 else -1
                msg = (b or {}).get("message", "")[:150] if isinstance(b, dict) else raw[:150]
                obs.append((tid, f"search{k}", s, c, f"hits={n} {msg}"))
            with lock:
                results.extend(obs)

        ts = [threading.Thread(target=worker, args=(i,)) for i in range(NTHREADS)]
        for t in ts: t.start()
        for t in ts: t.join()

        for o in sorted(results):
            print(o)

        search_codes = Counter(o[3] for o in results if o[1].startswith("search"))
        print("search code distribution:", dict(search_codes))
        defects = [o for o in results if o[1].startswith("search") and (o[2] >= 500 or o[3] == 65535)]
        # also flag: code 200 but 0 hits (20 rows exist) — silent empty during race
        empties = [o for o in results if o[1].startswith("search") and o[3] == 200 and "hits=0 " in str(o[4])]
        if defects:
            for d in defects:
                print("SUSPECT 5xx/65535:", d)
            print("VERDICT: DEFECT_FOUND")
        elif empties:
            for d in empties:
                print("SUSPECT silent-empty during concurrent load:", d)
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
