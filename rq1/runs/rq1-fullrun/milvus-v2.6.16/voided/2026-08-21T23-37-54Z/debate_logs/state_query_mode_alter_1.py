# script_id: state_query_mode_alter_1
# Attack: 策略2(生命周期一致性)+query_mode<->index 状态耦合 (milvus_range_collections_querymode_001)
# Constraints: milvus_range_collections_querymode_001, milvus_type_collections_create_009, milvus_inv_query_mode_001
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

CL = "st_qm_alter_1"
def cleanup():
    for c in [CL, CL + "_fw"]:
        try: sr("indexes/drop", {"collectionName": c, "indexName": "idx"})
        except Exception: pass
        try: sr("collections/drop", {"collectionName": c})
        except Exception: pass

def alter_qm(val):
    return sr("collections/alter_properties", {"collectionName": CL, "properties": {"query_mode": val}})

def get_qm():
    s, b, raw = sr("collections/describe", {"collectionName": CL})
    props = (b or {}).get("data", {}).get("properties") if isinstance(b, dict) else None
    if isinstance(props, dict):
        return props.get("query_mode")
    if isinstance(props, list):
        for p in props:
            if isinstance(p, dict) and p.get("key") == "query_mode":
                return p.get("value")
    return None

def create_index():
    return sr("indexes/create", {"collectionName": CL, "indexParams": [
        {"fieldName": "vector", "indexName": "idx", "indexType": "FLAT", "metricType": "L2"}]})

def drop_index():
    return sr("indexes/drop", {"collectionName": CL, "indexName": "idx"})

def wait_index():
    for _ in range(30):
        s, b, _r = sr("indexes/describe", {"collectionName": CL, "indexName": "idx"})
        d = (b or {}).get("data") if isinstance(b, dict) else None
        st = d.get("indexState") if isinstance(d, dict) else (d[0].get("indexState") if isinstance(d, list) and d else None)
        if st in ("Finished", "finished", 3):
            return True
        time.sleep(1)
    return False

def main():
    defects = []
    cleanup(); time.sleep(1)
    s, b, raw = sr("collections/create", {
        "collectionName": CL,
        "schema": {"fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "vector", "dataType": "FloatVector",
             "elementTypeParams": {"dim": "4"}}]}})
    print("create:", s, raw[:150])
    if not (isinstance(b, dict) and b.get("code") == 0):
        print("VERDICT: SCRIPT_ERROR"); cleanup(); sys.exit(2)

    # A: alter on index-less collection -> code 0, visible in describe
    s, b, raw = alter_qm("large_topk")
    print("A alter (no index):", s, raw[:200])
    if not (isinstance(b, dict) and b.get("code") == 0):
        defects.append(("alter query_mode on index-less collection rejected", raw[:150]))
    qm = get_qm(); print("A query_mode:", qm)
    if qm != "large_topk":
        defects.append(("query_mode not reflected in describe", str(qm)))

    # B: create vector index -> alter must be rejected code 702
    s, b, raw = create_index()
    print("B create index:", s, raw[:150])
    wait_index()
    s, b, raw = alter_qm("large_topk")
    print("B alter (with index):", s, raw[:250])
    code = b.get("code") if isinstance(b, dict) else None
    if code == 0:
        defects.append(("alter query_mode on indexed collection ACCEPTED (expected 702)", raw[:150]))
    elif code != 702:
        defects.append(("alter query_mode on indexed collection wrong code %s (expected 702)" % code, raw[:150]))

    # C: drop index -> alter must succeed again (coupling released)
    s, b, raw = drop_index()
    print("C drop index:", s, raw[:120]); time.sleep(2)
    s, b, raw = alter_qm("large_topk")
    print("C alter (after drop):", s, raw[:250])
    if not (isinstance(b, dict) and b.get("code") == 0):
        defects.append(("alter query_mode after index drop still rejected (stale coupling)", raw[:150]))

    # D: invalid value rejected (never accepted)
    s, b, raw = alter_qm("bogus")
    print("D alter bogus:", s, raw[:250])
    if isinstance(b, dict) and b.get("code") == 0:
        defects.append(("invalid query_mode value accepted", raw[:150]))

    # D2: FORWARD BYPASS — alter query_mode FIRST, then create vector index.
    # If index creation succeeds, the 702 gate is one-directional and the
    # "query_mode locked by index" invariant is unenforceable (contract gap).
    s, b, raw = sr("collections/create", {"collectionName": CL + "_fw",
        "schema": {"fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "vector", "dataType": "FloatVector",
             "elementTypeParams": {"dim": "4"}}]}})
    print("D2 create fw:", s, raw[:120])
    s, b, raw = alter_qm.__func__ if False else sr("collections/alter_properties",
        {"collectionName": CL + "_fw", "properties": {"query_mode": "large_topk"}})
    print("D2 alter first:", s, raw[:150])
    s, b, raw = sr("indexes/create", {"collectionName": CL + "_fw", "indexParams": [
        {"fieldName": "vector", "indexName": "idx", "indexType": "FLAT", "metricType": "L2"}]})
    print("D2 index AFTER large_topk:", s, raw[:200])
    if isinstance(b, dict) and b.get("code") == 0:
        defects.append(("FORWARD BYPASS: index created on collection already in large_topk query_mode; 702 gate one-directional", raw[:150]))
    try:
        sr("indexes/drop", {"collectionName": CL + "_fw", "indexName": "idx"})
        sr("collections/drop", {"collectionName": CL + "_fw"})
    except Exception:
        pass

    # E: load interplay: after load, alter query_mode (no index) — contract only gates index; check behavior
    s, b, raw = sr("collections/load", {"collectionName": CL})
    print("E load:", s, raw[:120])
    s, b, raw = alter_qm("large_topk")
    print("E alter after load:", s, raw[:250])
    code = b.get("code") if isinstance(b, dict) else None
    print("E code:", code)

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
