# script_id: state_dbname_isolation_1
# Attack: dbName 级隔离状态一致性（跨 db 集合可见性/同名冲突/drop db 行为）
# Constraints: milvus_state_collections_create_002, milvus_inv_created_visible_001, milvus_inv_dropped_absent_001
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
        r = requests.post(BASE + "/v2/vectordb/" + path, json=body if body is not None else {}, headers=H, timeout=60)
        raw = r.text
        try:
            b = r.json()
        except Exception:
            b = None
        return r.status_code, b, raw
    except Exception as e:
        return -1, None, str(e)

DB = "st_db_iso_1"
CL = "shared_name"

def cleanup():
    for dbn in [DB, None]:
        try: sr("collections/drop", {"collectionName": CL, **({"dbName": dbn} if dbn else {})})
        except Exception: pass
    try: sr("databases/drop", {"dbName": DB})
    except Exception: pass

def main():
    defects = []
    cleanup(); time.sleep(1)

    s, b, raw = sr("databases/create", {"dbName": DB})
    print("db create:", s, raw[:200])
    if not (isinstance(b, dict) and b.get("code") == 0):
        # maybe exists
        s2, b2, r2 = sr("databases/describe", {"dbName": DB})
        print("db describe:", s2, r2[:200])

    coll_body = {"collectionName": CL, "dimension": 4, "idType": "Int64", "metricType": "L2"}

    # A: same collection name in default db and custom db -> both should coexist
    s, b, raw = sr("collections/create", coll_body)
    print("create in default:", s, raw[:200])
    s, b, raw = sr("collections/create", {**coll_body, "dbName": DB})
    print("create same name in", DB, ":", s, raw[:200])
    if not (isinstance(b, dict) and b.get("code") == 0):
        defects.append(("same-name collection in different db rejected", raw[:150]))

    # B: list isolation
    s, b, raw = sr("collections/list", {})
    d=(b or {}).get("data") if isinstance(b,dict) else None
    names_def = set((d.get("collectionNames") if isinstance(d,dict) else d) or [])
    s, b, raw = sr("collections/list", {"dbName": DB})
    d=(b or {}).get("data") if isinstance(b,dict) else None
    names_db = set((d.get("collectionNames") if isinstance(d,dict) else d) or [])
    print("default list contains CL:", CL in names_def, "| db list contains CL:", CL in names_db, "| db list size:", len(names_db))
    if CL not in names_db:
        defects.append(("collection in custom db not listed via dbName list", str(names_db)[:150]))
    if CL in names_db and len(names_db) > 1 and names_db == names_def:
        defects.append(("dbName list identical to default list (no isolation)", str(names_db)[:150]))

    # C: has/describe isolation
    s, b, raw = sr("collections/has", {"collectionName": CL, "dbName": DB})
    print("has in db:", s, raw[:150])
    if not (isinstance(b, dict) and (b.get("data") or {}).get("has") is True):
        defects.append(("has=false for existing collection in custom db", raw[:150]))

    # D: drop in custom db must NOT affect default-db same-name collection
    s, b, raw = sr("collections/drop", {"collectionName": CL, "dbName": DB})
    print("drop in db:", s, raw[:150])
    time.sleep(1)
    s, b, raw = sr("collections/has", {"collectionName": CL})
    print("has default after db-side drop:", s, raw[:150])
    if not (isinstance(b, dict) and (b.get("data") or {}).get("has") is True):
        defects.append(("default-db collection affected by drop of same-name in other db", raw[:150]))
    s, b, raw = sr("collections/has", {"collectionName": CL, "dbName": DB})
    if (isinstance(b, dict) and (b.get("data") or {}).get("has") is True):
        defects.append(("dropped collection in custom db still visible", raw[:150]))

    # E: drop db that still contains a collection
    s, b, raw = sr("collections/create", {**coll_body, "dbName": DB})
    print("recreate in db:", s, raw[:150])
    s, b, raw = sr("databases/drop", {"dbName": DB})
    print("drop non-empty db:", s, raw[:250])
    if isinstance(b, dict) and b.get("code") == 0:
        s2, b2, r2 = sr("databases/describe", {"dbName": DB})
        still = not (isinstance(b2, dict) and b2.get("code") != 0)
        print("db after drop describe:", r2[:150])
        if still:
            defects.append(("drop of non-empty db reported success but db still exists", r2[:150]))
        else:
            defects.append(("drop of NON-EMPTY db succeeded silently (data loss risk, expected rejection)", ""))
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
