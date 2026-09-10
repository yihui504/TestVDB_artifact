# state_r2_insert_search_visibility_005.py
# Attack: insert->立即 search/query 的可见性时序（Bounded 一致性面）+ get_stats rowCount 漂移
# Strategy: state_consistency | Param: consistency
# Constraint: milvus_bc_consistency_bounded, milvus_inv_count_consistency
# Source: https://github.com/milvus-io/milvus/blob/v2.3.22/internal/distributed/proxy/httpserver/handler_v1.go (v2.3.22)
import os, time
import requests

BASE = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530")
H = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}
CLS = "r2_vis_005"

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

        defects = []
        base = 0
        for batch in range(5):
            ids = [base + i for i in range(10)]
            base += 10
            s, b, raw = req("POST", "v2/vectordb/entities/insert",
                            {"collectionName": CLS,
                             "data": [{"id": i, "vector": [0.1, 0.2, 0.3, 0.4]} for i in ids]})
            ic = code(b)
            # immediate visibility probes (no flush)
            s1, b1, raw1 = req("POST", "v2/vectordb/entities/search",
                               {"collectionName": CLS, "data": [[0.1, 0.2, 0.3, 0.4]], "limit": 100})
            s2, b2, raw2 = req("POST", "v2/vectordb/entities/query",
                               {"collectionName": CLS, "filter": f"id == {ids[-1]}",
                                "outputFields": ["id"]})
            s3, b3, raw3 = req("POST", "v2/vectordb/collections/get_stats",
                               {"collectionName": CLS})
            sc = code(b1)
            hits = len((b1 or {}).get("data") or []) if sc == 200 else -1
            qc = code(b2)
            qhits = len((b2 or {}).get("data") or []) if qc == 200 else -1
            rowc = ((b3 or {}).get("data") or {}).get("rowCount") if code(b3) == 200 else None
            print(f"batch{batch}: insert_code={ic} | search_code={sc} hits={hits} | "
                  f"query_code={qc} qhits={qhits} | rowCount={rowc} (expected_total={base})")
            # observation windows per timing discipline (not aggregated away)
            if sc == 200 and hits > base:
                defects.append((batch, "search hits exceed inserted count", hits, base))
            if qc == 200 and qhits > 1:
                defects.append((batch, "query id==X returned multiple rows", qhits))
            if rowc is not None and rowc > base:
                defects.append((batch, "rowCount exceeds inserts", rowc, base))
        # wait for bounded staleness window (default 5s) then final check
        time.sleep(6)
        s1, b1, _ = req("POST", "v2/vectordb/entities/search",
                        {"collectionName": CLS, "data": [[0.1, 0.2, 0.3, 0.4]], "limit": 100})
        s3, b3, _ = req("POST", "v2/vectordb/collections/get_stats", {"collectionName": CLS})
        final_hits = len((b1 or {}).get("data") or []) if code(b1) == 200 else -1
        final_rc = ((b3 or {}).get("data") or {}).get("rowCount")
        print(f"final (after 6s): search hits={final_hits} rowCount={final_rc} expected={base}")
        if final_hits != base or (final_rc is not None and final_rc != base):
            defects.append(("final", "post-bounded-window inconsistency", final_hits, final_rc, base))

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
