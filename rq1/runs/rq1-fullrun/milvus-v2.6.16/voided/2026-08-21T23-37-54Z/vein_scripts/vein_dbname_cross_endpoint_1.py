# script_id: vein_dbname_cross_endpoint_1
# Vein: 同参数跨端点行为差 — dbName 在 create / list / has / describe / insert / aliases / drop db
# 对照组: default db 同操作（应成功） vs nonexistent dbName（应 code 800）
# Constraints: milvus_state_collections_create_002, milvus_bc_create_dbname_001
# source_url: .milvus-src-2616, doc_version: unknown
import os, sys, time
import requests

BASE = os.environ.get("TESTVDB_DB_URL")
TOKEN = os.environ.get("TESTVDB_DB_TOKEN", "root:Milvus")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
H = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}

def sr(path, body=None):
    try:
        r = requests.post(BASE + "/v2/vectordb/" + path, json=body if body is not None else {}, headers=H, timeout=60)
        raw = r.text
        try:
            b = r.json()
        except Exception:
            b = None
        return r.status_code, b, raw
    except Exception as e:
        return -1, None, str(e)

NODB = "no_such_db_vn"
CL = "vn_cl"

def cleanup():
    try: sr("collections/drop", {"collectionName": CL})
    except Exception: pass

def code_of(b):
    return b.get("code") if isinstance(b, dict) else None

def main():
    defects = []
    # matrix: endpoint x body-with-nonexistent-dbName -> expected code 800
    probes = [
        ("collections/create", {"collectionName": CL, "dbName": NODB, "dimension": 4, "idType": "Int64"}, 800),
        ("collections/list", {"dbName": NODB}, 800),
        ("collections/has", {"collectionName": CL, "dbName": NODB}, None),  # observe
        ("collections/describe", {"collectionName": CL, "dbName": NODB}, None),
        ("collections/drop", {"collectionName": CL, "dbName": NODB}, None),
        ("collections/load", {"collectionName": CL, "dbName": NODB}, None),
        ("collections/get_stats", {"collectionName": CL, "dbName": NODB}, None),
        ("collections/truncate", {"collectionName": CL, "dbName": NODB}, None),
        ("entities/insert", {"collectionName": CL, "dbName": NODB, "data": [{"id": 1, "vector": [0.1] * 4}]}, None),
        ("entities/query", {"collectionName": CL, "dbName": NODB, "filter": "id >= 0", "outputFields": ["id"]}, None),
        ("entities/search", {"collectionName": CL, "dbName": NODB, "data": [[0.1] * 4]}, None),
        ("entities/delete", {"collectionName": CL, "dbName": NODB, "filter": "id >= 0"}, None),
        ("aliases/create", {"aliasName": "vn_al", "collectionName": CL, "dbName": NODB}, None),
        ("aliases/list", {"dbName": NODB}, None),
        ("partitions/create", {"collectionName": CL, "partitionName": "vn_p", "dbName": NODB}, None),
        ("indexes/create", {"collectionName": CL, "dbName": NODB, "indexParams": [{"fieldName": "vector", "indexName": "i", "indexType": "FLAT", "metricType": "L2"}]}, None),
    ]
    codes = {}
    for path, body, expect in probes:
        s, b, raw = sr(path, body)
        c = code_of(b)
        codes[path] = c
        print("%-26s dbName=%s -> code=%s %s" % (path, NODB, c, str(b.get("message"))[:80] if isinstance(b, dict) else ""))
        if expect is not None and c != expect:
            defects.append(("%s with nonexistent dbName: code %s expected %s" % (path, c, expect), raw[:120]))
    # cross-endpoint comparison: anything that succeeded on a nonexistent db is an asymmetry
    ok_on_nodb = [p for p, c in codes.items() if c == 0]
    if ok_on_nodb:
        defects.append(("operations SUCCEED (code 0) against nonexistent dbName — idempotent-success semantics inconsistent with create's 800 gate: %s" % ok_on_nodb, ""))
    # check which claim collection-not-found (100/101) vs database-not-found (800)
    notdb = [p for p, c in codes.items() if c in (800,)]
    notcoll = [p for p, c in codes.items() if c in (100, 101, 65535)]
    print("code 800 (db-not-found):", notdb)
    print("code 100/101/65535 (coll-flavored):", notcoll)

    # control: same ops on default db (existence confirmed) behave sanely
    s, b, raw = sr("collections/create", {"collectionName": CL, "dimension": 4, "idType": "Int64"})
    print("CONTROL create default:", s, raw[:100])
    s, b, raw = sr("collections/list", {})
    print("CONTROL list default ok:", code_of(b))
    cleanup()
    for d in defects: print("DEFECT:", d)
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
