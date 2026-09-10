# script_id: vein_query_mode_maturity_1
# Vein: discover-then-deepen — query_mode (2.6 新代码路径) 校验成熟度
# 对照组: (1) alter_properties query_mode=bogus (已知校验存在) vs (2) create-time properties.query_mode (怀疑无校验)
# + (3) alter_properties 携带任意未知 key 是否被写入并回显 (unvalidated pass-through 同族)
# Constraints: milvus_type_collections_create_009, milvus_type_collections_create_010, milvus_range_collections_querymode_001
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

CL_A = "vn_qm_ctl"   # control: alter path
CL_B = "vn_qm_ct"    # treatment: create-time properties
CL_C = "vn_qm_junk"  # treatment: unknown keys via alter

def cleanup():
    for c in [CL_A, CL_B, CL_C]:
        try: sr("collections/drop", {"collectionName": c})
        except Exception: pass

def props_of(name):
    s, b, raw = sr("collections/describe", {"collectionName": name})
    d = (b or {}).get("data", {}) if isinstance(b, dict) else {}
    return d.get("properties")

SCHEMA = {"fields": [
    {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
    {"fieldName": "vector", "dataType": "FloatVector", "elementTypeParams": {"dim": "4"}}]}

def main():
    defects = []
    cleanup(); time.sleep(1)

    # --- CONTROL: alter path validates query_mode ---
    sr("collections/create", {"collectionName": CL_A, "schema": SCHEMA})
    s, b, raw = sr("collections/alter_properties", {"collectionName": CL_A,
        "properties": {"query_mode": "bogus"}})
    print("CONTROL alter query_mode=bogus:", s, raw[:200])
    ctrl_rejected = isinstance(b, dict) and b.get("code") != 0
    if not ctrl_rejected:
        defects.append(("CONTROL: alter path stopped validating query_mode (baseline broken)", raw[:150]))

    # --- TREATMENT 1: create-time properties.query_mode (bogus AND valid) ---
    for val in ["bogus", "large_topk"]:
        s, b, raw = sr("collections/create", {"collectionName": CL_B, "schema": SCHEMA,
            "properties": {"query_mode": val}})
        print("T1 create properties.query_mode=%s:" % val, s, raw[:200])
        code = b.get("code") if isinstance(b, dict) else None
        if code == 0 and val == "bogus":
            defects.append(("T1: create-time properties.query_mode='bogus' ACCEPTED (code 0) while alter path validates — cross-endpoint validation asymmetry", raw[:150]))
        if code == 0 and val == "large_topk":
            props = props_of(CL_B)
            has_qm = any(p.get("key") == "query_mode" for p in (props or []) if isinstance(p, dict)) if isinstance(props, list) else "query_mode" in (props or {})
            print("T1 persisted:", has_qm, str(props)[:120])
            if not has_qm:
                defects.append(("T1: create-time properties.query_mode accepted but silently discarded (no effect, no error)", str(props)[:150]))
        try: sr("collections/drop", {"collectionName": CL_B})
        except Exception: pass

    # --- TREATMENT 2: unknown keys via alter_properties persist unvalidated ---
    sr("collections/create", {"collectionName": CL_C, "schema": SCHEMA})
    s, b, raw = sr("collections/alter_properties", {"collectionName": CL_C,
        "properties": {"junk_key_abc": "junk_value", "query_mod": "large_topk", "nprobe": 0}})
    print("T2 alter unknown keys:", s, raw[:150])
    props = props_of(CL_C)
    print("T2 props after:", str(props)[:200])
    persisted = [p.get("key") for p in (props or []) if isinstance(p, dict)] if isinstance(props, list) else list((props or {}).keys())
    junk = [k for k in persisted if k in ("junk_key_abc", "query_mod", "nprobe")]
    if junk:
        defects.append(("T2: unknown properties %s persisted to collection metadata via alter_properties (unvalidated write)" % junk, str(props)[:150]))

    # --- TREATMENT 3: same junk at create time — same pass-through? (cross-endpoint compare) ---
    s, b, raw = sr("collections/create", {"collectionName": CL_B, "schema": SCHEMA,
        "properties": {"junk_key_abc": "junk_value"}})
    props = props_of(CL_B)
    persisted = [p.get("key") for p in (props or []) if isinstance(p, dict)] if isinstance(props, list) else list((props or {}).keys())
    print("T3 create-time junk persisted:", persisted)
    # asymmetry direction either way is the finding:
    create_junk = "junk_key_abc" in persisted
    alter_junk = "junk_key_abc" in junk
    if create_junk != alter_junk:
        defects.append(("T3: create vs alter_properties treat unknown properties asymmetrically (create=%s alter=%s)" % (create_junk, alter_junk), ""))

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
