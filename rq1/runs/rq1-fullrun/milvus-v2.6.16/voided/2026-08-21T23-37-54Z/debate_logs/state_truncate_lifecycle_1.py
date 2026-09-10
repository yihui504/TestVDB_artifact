# script_id: state_truncate_lifecycle_1
# Attack: 策略1(CRUD count)+truncate 生命周期回归
# Constraints: milvus_state_collections_truncate_001, milvus_inv_truncate_count_001, milvus_inv_count_consistency_001
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

CL = "st_trunc_1"

def cleanup():
    try: sr("collections/drop", {"collectionName": CL})
    except Exception: pass

def row_count():
    s, b, raw = sr("collections/get_stats", {"collectionName": CL})
    d = (b or {}).get("data") if isinstance(b, dict) else None
    rc = d.get("rowCount") if isinstance(d, dict) else d.get("row_count") if isinstance(d, dict) else None
    return rc, raw

def main():
    defects = []
    cleanup(); time.sleep(1)
    s, b, raw = sr("collections/create", {"collectionName": CL, "dimension": 4, "idType": "Int64", "metricType": "L2"})
    print("create:", s, raw[:150])

    # insert 100 rows
    rows = [{"id": i, "vector": [0.01 * (i % 10)] * 4} for i in range(100)]
    s, b, raw = sr("entities/insert", {"collectionName": CL, "data": rows})
    print("insert:", s, raw[:150])
    if not (isinstance(b, dict) and b.get("code") == 0):
        print("VERDICT: SCRIPT_ERROR"); cleanup(); sys.exit(2)

    s, b, raw = sr("collections/load", {"collectionName": CL})
    print("load:", s, raw[:150])

    # count after flush (Bounded)
    s, b, raw = sr("collections/flush", {"collectionName": CL})
    print("flush:", s, raw[:150])
    time.sleep(2)
    sr("collections/flush", {"collectionName": CL}); time.sleep(3)
    rc0, raw = row_count()
    print("count after insert:", rc0, raw[:150])
    if rc0 is not None and rc0 != 100:
        defects.append(("count after 100 inserts = %s" % rc0, raw[:150]))

    # query count with consistency Strong
    s, b, raw = sr("entities/query", {"collectionName": CL, "filter": "id >= 0",
                                      "outputFields": ["id"], "consistencyLevel": "Strong"})
    n = len(((b or {}).get("data") or [])) if isinstance(b, dict) else -1
    print("query rows:", n, raw[:120])

    # truncate
    s, b, raw = sr("collections/truncate", {"collectionName": CL})
    print("truncate:", s, raw[:200])
    if not (isinstance(b, dict) and b.get("code") == 0):
        defects.append(("truncate failed", raw[:150]))
    time.sleep(2)
    rc1, raw = row_count()
    print("count after truncate:", rc1, raw[:150])
    if rc1 is not None and rc1 != 0:
        defects.append(("row_count after truncate = %s (expected 0)" % rc1, raw[:150]))

    # query after truncate (Strong) must return 0 rows
    s, b, raw = sr("entities/query", {"collectionName": CL, "filter": "id >= 0",
                                      "outputFields": ["id"], "consistencyLevel": "Strong"})
    n = len(((b or {}).get("data") or [])) if isinstance(b, dict) else -1
    print("query rows after truncate:", n, raw[:120])
    if n > 0:
        defects.append(("query still returns %s rows after truncate" % n, raw[:150]))

    # schema + load state preserved
    s, b, raw = sr("collections/describe", {"collectionName": CL})
    dd = (b or {}).get("data") if isinstance(b, dict) else {}
    dd = dd[0] if isinstance(dd, list) and dd else (dd if isinstance(dd, dict) else {})
    flds = dd.get("fields")
    print("schema after truncate:", [f.get("fieldName") for f in (flds or [])])
    if not flds:
        defects.append(("schema lost after truncate", raw[:150]))
    s, b, raw = sr("collections/get_load_state", {"collectionName": CL})
    print("load state after truncate:", s, raw[:200])

    # re-insert after truncate + FLUSH: rowCount must reflect visible rows
    # (live-observed v2.6.16: post-truncate flush reports rowCount=0 while Strong query sees the rows)
    s, b, raw = sr("entities/insert", {"collectionName": CL, "data": rows[:10]})
    print("re-insert 10:", s, raw[:150])
    s, b, raw = sr("entities/query", {"collectionName": CL, "filter": "id >= 0",
                                      "outputFields": ["id"], "consistencyLevel": "Strong"})
    vis = len(((b or {}).get("data") or [])) if isinstance(b, dict) else -1
    print("visible rows (Strong) after re-insert:", vis)
    sr("collections/flush", {"collectionName": CL}); time.sleep(4)
    rc2, raw = row_count()
    print("rowCount after truncate+reinsert+flush:", rc2)
    if rc2 is not None and vis > 0 and rc2 != vis:
        defects.append(("get_stats rowCount=%s while Strong query sees %s rows after post-truncate flush" % (rc2, vis), raw[:150]))

    # truncate nonexistent -> proper code 100
    s, b, raw = sr("collections/truncate", {"collectionName": "no_such_coll_xyz"})
    print("truncate nonexistent:", s, raw[:200])
    if isinstance(b, dict) and b.get("code") == 0:
        defects.append(("truncate nonexistent collection accepted", raw[:150]))

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
