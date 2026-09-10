# state_r2_load_immediacy_001.py
# Attack: load 完成即时性 — load 返回成功后立即 search 的行为矩阵（延迟梯度 0/10/50/100ms × 多轮）
# Strategy: index_state / load_lifecycle timing | Param: load
# Constraint: milvus_state_release_001, milvus_state_search_001, milvus_inv_load_lifecycle
# Source: https://github.com/milvus-io/milvus/blob/v2.3.22/internal/distributed/proxy/httpserver/handler_v2.go (doc_version v2.3.22)
import os, sys, time, json
import requests

BASE = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530")
H = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}
CLS = "r2_load_imm_001"

def req(method, path, body=None):
    try:
        r = requests.request(method, BASE + "/" + path, headers=H,
                              json=body if body is not None else None, timeout=30)
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
                        {"collectionName": CLS,
                         "schema": {"fields": [
                             {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
                             {"fieldName": "vector", "dataType": "FloatVector",
                              "elementTypeParams": {"dim": 4}}]},
                         "indexParams": [{"fieldName": "vector", "indexName": "idx",
                                          "metricType": "L2",
                                          "params": {"index_type": "FLAT"}}]})
        print("create:", s, raw[:200])
        if code(b) != 200:
            print("VERDICT: SCRIPT_ERROR"); return
        s, b, raw = req("POST", "v2/vectordb/entities/insert",
                        {"collectionName": CLS, "data": [
                            {"id": i, "vector": [0.1 * i, 0.2, 0.3, 0.4]} for i in range(10)]})
        print("insert:", s, raw[:200])

        observations = []
        bad = []
        for rnd in range(5):
            # release -> fresh load cycle each round
            s, b, raw = req("POST", "v2/vectordb/collections/release", {"collectionName": CLS})
            print(f"round{rnd} release: {s} {raw[:120]}")
            time.sleep(0.2)
            s, b, raw = req("POST", "v2/vectordb/collections/load", {"collectionName": CLS})
            load_code = code(b)
            print(f"round{rnd} load: {s} code={load_code} {raw[:120]}")
            if s != 200 or load_code != 200:
                bad.append((rnd, "load_failed", s, load_code, raw[:150]))
                continue
            for delay in (0.0, 0.01, 0.05, 0.10):
                time.sleep(delay)
                s, b, raw = req("POST", "v2/vectordb/entities/search",
                                {"collectionName": CLS, "data": [[0.1, 0.2, 0.3, 0.4]], "limit": 3})
                c = code(b)
                msg = (b or {}).get("message", "")[:120] if isinstance(b, dict) else raw[:120]
                observations.append((rnd, delay, s, c, msg))
                print(f"round{rnd} delay={delay}s search: http={s} code={c} msg={msg}")
                # defect signals: HTTP 5xx, code 65535 UnexpectedError, or success envelope with zero hits masking load state
                if s >= 500 or c == 65535:
                    bad.append((rnd, delay, "unexpected_error", s, c, msg))
                elif c == 200 and isinstance(b, dict):
                    n = len(b.get("data") or [])
                    if n == 0:
                        # 10 rows inserted; loaded search returning empty may indicate stale serving path
                        bad.append((rnd, delay, "loaded_but_empty", s, c, msg))
                elif c not in (200, 101, 100, 1800, 1801, 1802, 1804):
                    bad.append((rnd, delay, "odd_code", s, c, msg))

        print("total observations:", len(observations))
        if bad:
            for x in bad:
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
