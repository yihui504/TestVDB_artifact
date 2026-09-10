# state_r2_alias_lifecycle_race_008.py
# Attack: 别名生命周期竞态 — drop 底层 collection 后 alias 的残留状态 + alter 指向已删集合 + alias 上 search
# Strategy: state_consistency / lifecycle | Param: alias
# Constraint: milvus_inv_dropped_absent (alias 应随 target 消失或显式报 not found)
# Source: https://github.com/milvus-io/milvus/blob/v2.3.22/internal/distributed/proxy/httpserver/handler_v2.go (v2.3.22)
import os, time
import requests

BASE = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530")
H = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}
CLS = "r2_alias_a_008"
CLS_B = "r2_alias_b_008"
ALIAS = "r2_alias_x_008"

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

def mkcol(name):
    req("POST", "v2/vectordb/collections/drop", {"collectionName": name})
    s, b, raw = req("POST", "v2/vectordb/collections/create",
                    {"collectionName": name, "schema": {"fields": [
                        {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
                        {"fieldName": "vector", "dataType": "FloatVector",
                         "elementTypeParams": {"dim": 4}}]},
                     "indexParams": [{"fieldName": "vector", "indexName": "idx",
                                      "metricType": "L2", "params": {"index_type": "FLAT"}}]})
    return code(b)

def main():
    try:
        if mkcol(CLS) != 200 or mkcol(CLS_B) != 200:
            print("VERDICT: SCRIPT_ERROR"); return
        req("POST", "v2/vectordb/entities/insert",
            {"collectionName": CLS, "data": [{"id": i, "vector": [0.1, 0.2, 0.3, 0.4]} for i in range(5)]})
        time.sleep(0.5)

        defects = []
        # 1) alias on A, drop A -> alias residue
        req("POST", "v2/vectordb/aliases/drop", {"aliasName": ALIAS})
        s, b, raw = req("POST", "v2/vectordb/aliases/create",
                        {"aliasName": ALIAS, "collectionName": CLS})
        print("alias create:", s, raw[:150])
        s, b, raw = req("POST", "v2/vectordb/collections/drop", {"collectionName": CLS})
        print("drop target:", s, raw[:150])
        time.sleep(0.5)
        s, b, raw = req("POST", "v2/vectordb/aliases/describe", {"aliasName": ALIAS})
        print("alias describe after target drop:", s, raw[:250])
        if code(b) == 200:
            defects.append(("alias survives dropped target (describe still 200)", raw[:200]))
        # search via alias to dropped target — must be business error (100-family), not 5xx/65535
        s, b, raw = req("POST", "v2/vectordb/entities/search",
                        {"collectionName": ALIAS, "data": [[0.1, 0.2, 0.3, 0.4]], "limit": 1})
        print("search via dangling alias:", s, raw[:250])
        if s >= 500 or code(b) == 65535:
            defects.append(("search via dangling alias 5xx/65535", s, code(b), raw[:200]))

        # 2) alter alias to non-existent target
        s, b, raw = req("POST", "v2/vectordb/aliases/alter",
                        {"aliasName": ALIAS, "collectionName": "no_such_coll_xyz"})
        print("alter alias to missing collection:", s, raw[:250])
        if code(b) == 200:
            defects.append(("alter alias to non-existent target accepted (Type1)", raw[:200]))

        # 3) alias race window: rapid alter between A-recreated and B while searching
        mkcol(CLS)
        req("POST", "v2/vectordb/entities/insert",
            {"collectionName": CLS, "data": [{"id": i, "vector": [0.1, 0.2, 0.3, 0.4]} for i in range(5)]})
        for i in range(10):
            tgt = CLS if i % 2 == 0 else CLS_B
            s, b, raw = req("POST", "v2/vectordb/aliases/alter",
                            {"aliasName": ALIAS, "collectionName": tgt})
            s2, b2, raw2 = req("POST", "v2/vectordb/entities/search",
                               {"collectionName": ALIAS, "data": [[0.1, 0.2, 0.3, 0.4]], "limit": 1})
            print(f"race iter{i}: alter->{tgt} code={code(b)} | alias search http={s2} code={code(b2)} {raw2[:120]}")
            if s2 >= 500 or code(b2) == 65535:
                defects.append((i, "alias flip race 5xx/65535", s2, code(b2), raw2[:150]))

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
        for op, body in (("v2/vectordb/aliases/drop", {"aliasName": ALIAS}),
                         ("v2/vectordb/collections/drop", {"collectionName": CLS}),
                         ("v2/vectordb/collections/drop", {"collectionName": CLS_B})):
            try:
                req("POST", op, body)
            except Exception:
                pass

if __name__ == "__main__":
    main()
