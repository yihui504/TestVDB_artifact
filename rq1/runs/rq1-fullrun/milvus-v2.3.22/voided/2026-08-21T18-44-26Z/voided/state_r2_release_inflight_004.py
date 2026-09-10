# state_r2_release_inflight_004.py
# Attack: release 与 in-flight search 的竞态 — search 正在执行时并发 release，观测 search 的行为
# Blindspot: BS-03 | Strategy: concurrent | Param: release
# Constraint: milvus_state_release_001, milvus_behavioral_error_envelope_001
# Source: https://github.com/milvus-io/milvus/blob/v2.3.22/pkg/util/merr/errors.go (v2.3.22)
import os, threading, time
from collections import Counter
import requests

BASE = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530")
H = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}
CLS = "r2_rel_inflight_004"

def req(method, path, body=None):
    try:
        r = requests.request(method, BASE + "/" + path, headers=H, json=body, timeout=30)
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
        time.sleep(0.5)

        results = []
        lock = threading.Lock()

        def searcher(tid):
            obs = []
            for k in range(15):
                s, b, raw = req("POST", "v2/vectordb/entities/search",
                                {"collectionName": CLS, "data": [[0.1, 0.2, 0.3, 0.4]], "limit": 5})
                c = code(b)
                msg = (b or {}).get("message", "")[:150] if isinstance(b, dict) else raw[:150]
                obs.append((tid, k, s, c, msg))
                time.sleep(0.01)
            with lock:
                results.extend(obs)

        def releaser():
            for k in range(5):
                time.sleep(0.03)
                s, b, raw = req("POST", "v2/vectordb/collections/release", {"collectionName": CLS})
                with lock:
                    results.append(("rel", k, s, code(b), raw[:120]))
                time.sleep(0.03)
                s, b, raw = req("POST", "v2/vectordb/collections/load", {"collectionName": CLS})
                with lock:
                    results.append(("load", k, s, code(b), raw[:120]))

        threads = [threading.Thread(target=searcher, args=(i,)) for i in range(4)] + [threading.Thread(target=releaser)]
        for t in threads: t.start()
        for t in threads: t.join()
        time.sleep(1.0)

        for o in sorted(results, key=str):
            print(o)
        codes = Counter(str(o[3]) for o in results if isinstance(o[0], int))
        print("search code distribution:", dict(codes))
        # defect: HTTP 5xx / 65535 UnexpectedError / connection reset during release race
        defects = [o for o in results if isinstance(o[0], int) and (o[2] >= 500 or o[2] == -1 or o[3] == 65535)]
        if defects:
            for d in defects:
                print("SUSPECT:", d)
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
