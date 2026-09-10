# script_id: state_upsert_delete_count_1
# Attack: 策略3(upsert 幂等)+策略2(delete 后一致性)+inv_upsert_atomic
# Constraints: milvus_inv_upsert_atomic_001, milvus_inv_count_consistency_001, milvus_bc_delete_invisibility_001
# source_url: .milvus-src-2616 (contract), doc_version: unknown
import os, sys, time
import requests

BASE = os.environ.get("TESTVDB_DB_URL")
TOKEN = os.environ.get("TESTVDB_DB_TOKEN", "root:Milvus")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
H = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}

def sr(path, body=None):
    try:
        r = requests.post(BASE + "/v2/vectordb/" + path, json=body if body is not None else {}, headers=H, timeout=120)
        raw = r.text
        try:
            b = r.json()
        except Exception:
            b = None
        return r.status_code, b, raw
    except Exception as e:
        return -1, None, str(e)

CL = "st_updel_1"

def cleanup():
    try: sr("collections/drop", {"collectionName": CL})
    except Exception: pass

def row_count():
    s, b, raw = sr("collections/get_stats", {"collectionName": CL})
    d = (b or {}).get("data") if isinstance(b, dict) else None
    return (d.get("rowCount") if isinstance(d, dict) else None), raw

def qcount():
    s, b, raw = sr("entities/query", {"collectionName": CL, "filter": "id >= 0",
                                      "outputFields": ["count(*)"] if False else ["id"], "consistencyLevel": "Strong"})
    return len(((b or {}).get("data") or [])) if isinstance(b, dict) else -1

def main():
    defects = []
    cleanup(); time.sleep(1)
    s, b, raw = sr("collections/create", {"collectionName": CL, "dimension": 4, "idType": "Int64", "metricType": "L2"})
    print("create:", s, raw[:150])
    s, b, raw = sr("entities/insert", {"collectionName": CL,
        "data": [{"id": i, "vector": [0.1, 0.2, 0.3, 0.4]} for i in range(10)]})
    print("insert 10:", s, raw[:150])
    s, b, raw = sr("collections/load", {"collectionName": CL})
    print("load:", s, raw[:120])
    time.sleep(1)
    n0 = qcount(); print("qcount:", n0)

    # A: upsert same id twice (idempotent count) + last-write-wins vector
    for v in [0.9, 0.5]:
        s, b, raw = sr("entities/upsert", {"collectionName": CL,
            "data": [{"id": 5, "vector": [v, v, v, v]}]})
        print("upsert id5 v=%s:" % v, s, raw[:120])
    n1 = qcount(); print("qcount after 2 upserts:", n1)
    if n1 != n0:
        defects.append(("count changed after upsert of existing id: %s -> %s" % (n0, n1), ""))
    s, b, raw = sr("entities/get", {"collectionName": CL, "id": 5, "outputFields": ["vector"]})
    vec = ((b or {}).get("data") or [{}])[0].get("vector") if isinstance(b, dict) and (b.get("data") or []) else None
    print("id5 vector after upserts:", vec)
    if vec is not None and abs(vec[0] - 0.5) > 1e-6:
        defects.append(("last-write-wins violated: vector[0]=%s expected 0.5" % vec[0], str(vec)))

    # B: upsert nonexistent id -> inserts (count +1)
    s, b, raw = sr("entities/upsert", {"collectionName": CL,
        "data": [{"id": 1000, "vector": [0.7] * 4}]})
    print("upsert new id:", s, raw[:120])
    n2 = qcount(); print("qcount after upsert new:", n2)
    if n2 != n1 + 1:
        defects.append(("upsert of new id changed count by != 1: %s -> %s" % (n1, n2), ""))

    # C: delete by filter then query same filter -> 0 rows
    s, b, raw = sr("entities/delete", {"collectionName": CL, "filter": "id in [0,1,2]"})
    print("delete:", s, raw[:120])
    s, b, raw = sr("entities/query", {"collectionName": CL, "filter": "id in [0,1,2]",
                                      "outputFields": ["id"], "consistencyLevel": "Strong"})
    n3 = len(((b or {}).get("data") or [])) if isinstance(b, dict) else -1
    print("deleted rows still visible:", n3, raw[:150])
    if n3 > 0:
        defects.append(("deleted entities still returned by query: %s" % n3, raw[:150]))

    # D: re-insert same ids after delete -> count correct (no duplicate)
    s, b, raw = sr("entities/insert", {"collectionName": CL,
        "data": [{"id": i, "vector": [0.1] * 4} for i in range(3)]})
    print("re-insert deleted ids:", s, raw[:120])
    n4 = qcount(); print("qcount after re-insert:", n4)
    if n4 != n2:
        defects.append(("re-insert of deleted ids count mismatch: %s vs expected %s" % (n4, n2), ""))

    # E: delete nonexistent ids (no-op) -> count unchanged
    s, b, raw = sr("entities/delete", {"collectionName": CL, "filter": "id in [99991,99992]"})
    print("delete nonexistent:", s, raw[:120])
    n5 = qcount()
    if n5 != n4:
        defects.append(("delete of nonexistent ids changed count: %s -> %s" % (n4, n5), ""))

    cleanup()
    for d in defects:
        print("DEFECT:", d)
    if defects:
        print("VERDICT: DEFECT_FOUND"); sys.exit(1)
    print("VERDICT: NO_DEFECT"); sys.exit(0)

try:
    main()
except Exception as e:
    print("EXC:", e)
    try: cleanup()
    except Exception: pass
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
