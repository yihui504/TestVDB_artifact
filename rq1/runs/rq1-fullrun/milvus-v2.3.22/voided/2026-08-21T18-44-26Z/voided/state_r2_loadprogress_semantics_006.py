# state_r2_loadprogress_semantics_006.py
# Attack: get_load_state loadProgress 语义 — 非 Loaded（Loading/非100 progress）状态下的 search/query/upsert 行为
# Strategy: state_observation | Param: load_state
# Constraint: milvus_range_get_load_state_001, milvus_state_search_001
# Source: https://github.com/milvus-io/milvus/blob/v2.3.22/internal/distributed/proxy/httpserver/handler_v2.go (v2.3.22)
import os, time
import requests

BASE = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530")
H = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}
CLS = "r2_prog_006"

def req(method, path, body=None):
    try:
        r = requests.request(method, BASE + "/" + path, headers=H, json=body, timeout=60)
        try:
            b = r.json()
        except Exception:
            b = None
        return r.status_code, b, r.text
    except Exception as e:
        return -1, None, str(e)

def code(b):
    return b.get("code") if isinstance(b, dict) else None

def ls_of(b):
    d = (b or {}).get("data") if isinstance(b, dict) else None
    if isinstance(d, dict):
        return d.get("loadState"), d.get("loadProgress")
    return None, None

def main():
    try:
        req("POST", "v2/vectordb/collections/drop", {"collectionName": CLS})
        # bigger data + HNSW to widen the Loading window
        s, b, raw = req("POST", "v2/vectordb/collections/create",
                        {"collectionName": CLS, "schema": {"fields": [
                            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
                            {"fieldName": "vector", "dataType": "FloatVector",
                             "elementTypeParams": {"dim": 64}}]},
                         "indexParams": [{"fieldName": "vector", "indexName": "idx",
                                          "metricType": "L2",
                                          "params": {"index_type": "HNSW", "M": 16, "efConstruction": 200}}]})
        print("create:", s, raw[:200])
        if code(b) != 200:
            print("VERDICT: SCRIPT_ERROR"); return
        inserted = 0
        for i in range(10):
            s, b, raw = req("POST", "v2/vectordb/entities/insert",
                            {"collectionName": CLS, "data": [
                                {"id": i * 500 + j, "vector": [0.01 * (j % 64) for j in range(64)]}
                                for j in range(500)]})
            if code(b) == 200:
                inserted += 500
        print("inserted:", inserted)
        req("POST", "v2/vectordb/collections/release", {"collectionName": CLS})
        time.sleep(1)

        s, b, raw = req("POST", "v2/vectordb/collections/load", {"collectionName": CLS})
        print("load:", s, raw[:120])

        defects = []
        observations = 0
        deadline = time.time() + 15
        while time.time() < deadline:
            s1, b1, _ = req("POST", "v2/vectordb/collections/get_load_state", {"collectionName": CLS})
            st, prog = ls_of(b1)
            if st == "Loaded":
                print(f"terminal: state={st} prog={prog} after {observations} obs")
                break
            observations += 1
            # while Loading / partial progress: probe operations
            s2, b2, raw2 = req("POST", "v2/vectordb/entities/search",
                               {"collectionName": CLS, "data": [[0.01 * (j % 64) for j in range(64)]],
                                "limit": 1})
            sc = code(b2)
            msg2 = (b2 or {}).get("message", "")[:120] if isinstance(b2, dict) else raw2[:120]
            s3, b3, raw3 = req("POST", "v2/vectordb/entities/insert",
                               {"collectionName": CLS, "data": [
                                   {"id": 900000 + observations, "vector": [0.5] * 64}]})
            ic = code(b3)
            msg3 = (b3 or {}).get("message", "")[:120] if isinstance(b3, dict) else raw3[:120]
            print(f"obs{observations}: state={st} prog={prog} | search http={s2} code={sc} ({msg2}) "
                  f"| insert http={s3} code={ic} ({msg3})")
            if prog is not None and isinstance(prog, int) and not (0 <= prog <= 100 or prog == -1):
                defects.append((observations, "loadProgress out of documented range", prog))
            if s2 >= 500 or sc == 65535:
                defects.append((observations, "search 5xx/65535 during Loading", s2, sc, msg2))
            if s3 >= 500 or ic == 65535:
                defects.append((observations, "insert 5xx/65535 during Loading", s3, ic, msg3))
            # envelope self-consistency: code!=200 but message empty, or code 200 with error-ish message
            if sc != 200 and sc is not None and not msg2.strip():
                defects.append((observations, "error code with empty message (envelope inconsistent)", sc))
            time.sleep(0.05)

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
