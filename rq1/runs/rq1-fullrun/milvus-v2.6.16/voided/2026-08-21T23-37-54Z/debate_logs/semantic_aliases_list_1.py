# script_id: semantic_aliases_list_1
# Attack: aliases+list/describe 语义——返回集合与绑定的正确性（跨 collection 重绑/删除目标后）
# Constraints: milvus_state_aliases_create_001, milvus_bc_crud_visibility_001
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

CA, CB = "sm_al_a", "sm_al_b"
AL = "sm_alias_x"

def cleanup():
    for op in [("aliases/drop", {"aliasName": AL})]:
        try: sr(*op)
        except Exception: pass
    for c in [CA, CB]:
        try: sr("collections/drop", {"collectionName": c})
        except Exception: pass

def main():
    defects = []
    cleanup(); time.sleep(1)
    for c in [CA, CB]:
        s, b, raw = sr("collections/create", {"collectionName": c, "dimension": 4, "idType": "Int64", "metricType": "L2"})
        print("create", c, ":", s, raw[:120])

    # A: create alias -> list contains it, describe points to CA
    s, b, raw = sr("aliases/create", {"aliasName": AL, "collectionName": CA})
    print("A alias create:", s, raw[:150])
    s, b, raw = sr("aliases/list", {})
    d = (b or {}).get("data") if isinstance(b, dict) else None
    # v2.6.16: data is a plain list of alias name strings
    names = d if isinstance(d, list) and all(isinstance(x, str) for x in d) else str(d)
    print("A alias list:", str(names)[:200])
    listed = AL in str(names)
    if not listed:
        defects.append(("alias not present in aliases/list after create", raw[:150]))
    s, b, raw = sr("aliases/describe", {"aliasName": AL})
    tgt = ((b or {}).get("data") or {}).get("collectionName") if isinstance(b, dict) and isinstance((b or {}).get("data"), dict) else str((b or {}).get("data"))[:80]
    print("A alias describe ->", tgt)
    if tgt != CA:
        defects.append(("alias describe points to %s, expected %s" % (tgt, CA), raw[:150]))

    # B: insert via alias lands in target collection
    s, b, raw = sr("entities/insert", {"collectionName": AL,
        "data": [{"id": 1, "vector": [0.1] * 4}]})
    print("B insert via alias:", s, raw[:150])
    s, b, raw = sr("collections/get_stats", {"collectionName": CA})
    print("B stats CA:", raw[:120])

    # C: alter alias to CB (rebind) -> describe follows, CA data intact
    s, b, raw = sr("aliases/alter", {"aliasName": AL, "collectionName": CB})
    print("C alias alter:", s, raw[:150])
    s, b, raw = sr("aliases/describe", {"aliasName": AL})
    tgt = ((b or {}).get("data") or {}).get("collectionName") if isinstance(b, dict) and isinstance((b or {}).get("data"), dict) else str((b or {}).get("data"))[:80]
    print("C describe after alter ->", tgt)
    if tgt != CB:
        defects.append(("alias did not rebind: still %s expected %s" % (tgt, CB), raw[:150]))

    # D: drop target collection CB while alias points to it
    s, b, raw = sr("collections/drop", {"collectionName": CB})
    print("D drop target CB:", s, raw[:150])
    s, b, raw = sr("aliases/describe", {"aliasName": AL})
    code = b.get("code") if isinstance(b, dict) else None
    print("D describe alias after target drop:", s, raw[:200])
    if code == 0:
        # dangling alias visible as success — check whether using it now errors sanely
        s2, b2, r2 = sr("collections/has", {"collectionName": AL})
        s3, b3, r3 = sr("entities/query", {"collectionName": AL, "filter": "id >= 0", "outputFields": ["id"]})
        print("D has via alias:", r2[:120], "| query via alias:", r3[:150])
        qcode = b3.get("code") if isinstance(b3, dict) else None
        if qcode == 0:
            defects.append(("query via dangling alias SUCCEEDS after target drop", r3[:150]))
    s, b, raw = sr("aliases/list", {})
    d = (b or {}).get("data") if isinstance(b, dict) else None
    print("D alias list after target drop:", str(d)[:200])
    if AL in str(d):
        defects.append(("dangling alias remains in list after target collection dropped (no cascade/gc)", str(d)[:150]))

    # E: alias list cross-db: alias created in custom db vs default list
    # (semantic: aliases are db-scoped; default list must not leak custom-db aliases)
    try:
        sr("databases/create", {"dbName": "sm_al_db"})
        sr("collections/create", {"collectionName": CA, "dbName": "sm_al_db", "dimension": 4, "idType": "Int64", "metricType": "L2"})
        s, b, raw = sr("aliases/create", {"aliasName": AL + "_db", "collectionName": CA, "dbName": "sm_al_db"})
        print("E alias in custom db:", s, raw[:150])
        s, b, raw = sr("aliases/list", {})
        d = (b or {}).get("data") if isinstance(b, dict) else None
        leak = (AL + "_db") in str(d)
        print("E default alias list leak:", leak)
        if leak:
            defects.append(("custom-db alias leaked into default-db aliases/list (db scoping violated)", str(d)[:150]))
        sr("collections/drop", {"collectionName": CA, "dbName": "sm_al_db"})
        sr("databases/drop", {"dbName": "sm_al_db"})
    except Exception as e:
        print("E skipped:", e)

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
