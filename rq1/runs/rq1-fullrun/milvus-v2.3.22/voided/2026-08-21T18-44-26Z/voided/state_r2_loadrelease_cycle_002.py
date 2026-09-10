# state_r2_loadrelease_cycle_002.py
# Attack: load->release->load 快速循环中 get_load_state 与实际可服务性（search）的一致性窗口
# Strategy: state_observation | Param: load_state
# Constraint: milvus_range_get_load_state_001, milvus_state_release_001
# Source: https://github.com/milvus-io/milvus/blob/v2.3.22/internal/distributed/proxy/httpserver/handler_v2.go (v2.3.22)
import os, time
import requests

BASE = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530")
H = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}
CLS = "r2_lr_cycle_002"

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

def state(b):
    d = (b or {}).get("data") if isinstance(b, dict) else None
    if isinstance(d, dict):
        return d.get("loadState"), d.get("loadProgress")
    return None, None

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
            {"collectionName": CLS, "data": [{"id": i, "vector": [0.1, 0.2, 0.3, 0.4]} for i in range(5)]})

        inconsistencies = []
        for i in range(20):
            act = "load" if i % 2 == 0 else "release"
            s, b, raw = req("POST", f"v2/vectordb/collections/{act}", {"collectionName": CLS})
            # immediately observe get_load_state + search back-to-back
            s1, b1, raw1 = req("POST", "v2/vectordb/collections/get_load_state", {"collectionName": CLS})
            s2, b2, raw2 = req("POST", "v2/vectordb/entities/search",
                               {"collectionName": CLS, "data": [[0.1, 0.2, 0.3, 0.4]], "limit": 1})
            ls, prog = state(b1)
            sc = code(b2)
            print(f"iter{i} {act}: op_code={code(b)} | load_state={ls} prog={prog} | search_code={sc}")
            # inconsistency: state says Loaded but search fails with not-loaded(101), or state NotLoad/Loading but search succeeds
            if act == "load":
                if ls == "Loaded" and sc == 101:
                    inconsistencies.append((i, "state=Loaded but search=101"))
                if sc >= 500 or sc == 65535:
                    inconsistencies.append((i, "search 5xx/65535 during load cycle", raw2[:150]))
            else:
                if ls in ("NotLoad", "Loading") and sc == 200:
                    inconsistencies.append((i, f"state={ls} but search=200 after release"))
            time.sleep(0.05)

        if inconsistencies:
            for x in inconsistencies:
                print("SUSPECT:", x)
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
