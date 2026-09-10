# script_id: semantic_insert_extra_keys_1
# Attack: insert 额外键（nprobe/searchParams）被忽略后 insert 行为是否完全等同 + 语义影响
# Constraints: milvus_type_entities_insert_002, milvus_type_collections_create_010
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

CL = "sm_ins_extra_1"

def cleanup():
    try: sr("collections/drop", {"collectionName": CL})
    except Exception: pass

def main():
    defects = []
    cleanup(); time.sleep(1)
    s, b, raw = sr("collections/create", {"collectionName": CL, "dimension": 4, "idType": "Int64", "metricType": "L2"})
    print("create:", s, raw[:150])

    # A: baseline insert
    rows = [{"id": i, "vector": [0.1, 0.2, 0.3, 0.4]} for i in range(10)]
    s, b, raw = sr("entities/insert", {"collectionName": CL, "data": rows})
    print("A baseline insert:", s, raw[:150])
    base_ok = isinstance(b, dict) and b.get("code") == 0

    # B: insert with extra keys nprobe=0 / searchParams junk — must behave identically
    variants = [
        {"nprobe": 0},
        {"nprobe": -5},
        {"searchParams": {"nprobe": 0}},
        {"search_params": {"ef": "junk"}},
        {"annsField": "vector"},
        {"unknownKey": {"deep": [1, 2, None]}},
    ]
    for vi, extra in enumerate(variants):
        rows2 = [{"id": 100 + vi * 10 + i, "vector": [0.1, 0.2, 0.3, 0.4]} for i in range(5)]
        s, b, raw = sr("entities/insert", {"collectionName": CL, "data": rows2, **extra})
        code = b.get("code") if isinstance(b, dict) else None
        print("B insert extra %s -> code %s" % (list(extra.keys()), code), raw[:120])
        if code != 0:
            defects.append(("insert with extra key %s REJECTED (code %s) while contract says ignored" % (list(extra.keys()), code), raw[:150]))

    # C: do extra keys affect stored data? query back
    sr("collections/load", {"collectionName": CL})
    s, b, raw = sr("entities/query", {"collectionName": CL, "filter": "id >= 100",
                                      "outputFields": ["id"], "consistencyLevel": "Strong"})
    n = len(((b or {}).get("data") or [])) if isinstance(b, dict) else -1
    print("C rows stored from extra-key inserts:", n, "(expected 30)")
    if n != 30:
        defects.append(("extra-key inserts stored %s/30 rows" % n, raw[:150]))
    s, b, raw = sr("entities/query", {"collectionName": CL, "filter": "id >= 0",
                                      "outputFields": ["id"], "consistencyLevel": "Strong"})
    total = len(((b or {}).get("data") or [])) if isinstance(b, dict) else -1
    print("C total rows:", total, "(expected 40)")
    if total != 40:
        defects.append(("total after extra-key inserts = %s/40" % total, raw[:150]))

    # D: extra keys must NOT relax validation — wrong dim must still fail
    s, b, raw = sr("entities/insert", {"collectionName": CL,
        "data": [{"id": 500, "vector": [0.1, 0.2]}], "nprobe": 0})
    code = b.get("code") if isinstance(b, dict) else None
    print("D wrong-dim + nprobe:", s, raw[:200])
    if code == 0:
        defects.append(("extra keys masked validation: wrong-dim insert accepted with nprobe present", raw[:150]))

    # E: upsert with same junk must be equivalent too
    s, b, raw = sr("entities/upsert", {"collectionName": CL,
        "data": [{"id": 0, "vector": [0.5, 0.5, 0.5, 0.5]}], "searchParams": {"nprobe": 0}})
    code = b.get("code") if isinstance(b, dict) else None
    print("E upsert extra:", s, raw[:150])
    if code != 0:
        defects.append(("upsert with extra key rejected (code %s)" % code, raw[:150]))

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
